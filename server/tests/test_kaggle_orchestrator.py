"""Plan K2 — backend-orchestrated Kaggle worker spawn (tests first).

Kaggle package absent in test env; a stub is installed into sys.modules
BEFORE importing the orchestrator — the orchestrator imports kaggle lazily
inside _api() so the server never hard-depends on it.
"""

import builtins
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.db import SessionLocal

DEPLOY_KAGGLE = Path(__file__).parents[2] / "deploy" / "kaggle"


class StubKaggleApi:
    """Stand-in for kaggle.api.kaggle_api_extended.KaggleApi."""

    instances: list = []
    status_result = "complete"
    push_error: Exception | None = None
    bump_error: Exception | None = None

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.status_result = "complete"
        cls.push_error = None
        cls.bump_error = None

    def __init__(self) -> None:
        self.pushed: list = []
        self.calls: list = []  # (method, arg) in call order
        StubKaggleApi.instances.append(self)

    def authenticate(self) -> None:
        pass

    def kernels_status(self, ref):
        return {"status": StubKaggleApi.status_result}

    def dataset_create_version(self, folder, version_notes=None):
        # kaggle 2.2.4: bump uploads FROM the folder — verify metadata at call time
        meta = json.loads((Path(folder) / "dataset-metadata.json").read_text())
        self.calls.append(("dataset_create_version", folder, meta["id"]))
        if StubKaggleApi.bump_error is not None:
            raise StubKaggleApi.bump_error
        return {"folder": folder}

    def kernels_push(self, path, **kwargs):
        self.calls.append(("kernels_push", path))
        if StubKaggleApi.push_error is not None:
            raise StubKaggleApi.push_error
        self.pushed.append((path, kwargs))
        return {"ref": path}


def _install_kaggle_stub() -> None:
    kaggle_pkg = types.ModuleType("kaggle")
    api_pkg = types.ModuleType("kaggle.api")
    ext = types.ModuleType("kaggle.api.kaggle_api_extended")
    ext.KaggleApi = StubKaggleApi
    kaggle_pkg.api = api_pkg
    api_pkg.kaggle_api_extended = ext
    sys.modules["kaggle"] = kaggle_pkg
    sys.modules["kaggle.api"] = api_pkg
    sys.modules["kaggle.api.kaggle_api_extended"] = ext


_install_kaggle_stub()

from app.services import kaggle_orchestrator as orch  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_orch_state(monkeypatch):
    monkeypatch.setattr(orch, "_last_spawn", 0.0)
    StubKaggleApi.reset()
    yield


@pytest.fixture
def kaggle_env(monkeypatch, tmp_path):
    # Plan K5: mode default is "batch" — these K2 tests pin "loop" to keep
    # exercising the legacy worker-kernel branch (dispatch covered here +
    # test_kaggle_batch_orchestrator.py).
    monkeypatch.setattr(settings, "kaggle_mode", "loop")
    monkeypatch.setattr(settings, "kaggle_username", "testuser")
    monkeypatch.setattr(settings, "kaggle_key", "testkey")
    monkeypatch.setattr(settings, "kaggle_kernel_ref", "testuser/img2text-worker")
    monkeypatch.setattr(settings, "kaggle_stage_src", str(DEPLOY_KAGGLE))
    monkeypatch.setattr(
        settings, "kaggle_stage_dir", str(tmp_path / "kaggle-kernel")
    )
    return settings


def _api() -> StubKaggleApi:
    return StubKaggleApi.instances[-1]


def _pushed() -> list:
    """All pushes across instances (each _api() call makes one instance)."""
    return [p for i in StubKaggleApi.instances for p in i.pushed]


async def test_spawn_when_kernel_complete_and_queue_has_jobs(kaggle_env, seed_job):
    assert await orch.ensure_worker(SessionLocal) is True
    api = _api()
    assert len(api.pushed) == 1
    stage_dir, kwargs = api.pushed[0]
    assert stage_dir == str(settings.kaggle_stage_dir)
    # P2: plain push — metadata carries accelerator; timeout kw inert (ceiling = platform)
    assert kwargs == {}
    assert (Path(stage_dir) / "kernel-metadata.json").is_file()
    # P2: dataset version bump BEFORE push (kernel runs dataset code, not kernel dir);
    # the bump receives the STAGED FOLDER (worker files + dataset-metadata w/ id)
    assert api.calls == [
        (
            "dataset_create_version",
            str(settings.kaggle_stage_dir),
            "testuser/img2text-worker-files",
        ),
        ("kernels_push", str(settings.kaggle_stage_dir)),
    ]

class LegacyStubKaggleApi:
    """Old-name API shape: datasets_create_version(owner, slug, version_note)."""

    def __init__(self) -> None:
        self.calls: list = []
        self.pushed: list = []

    def authenticate(self) -> None:
        pass

    def kernels_status(self, ref):
        return {"status": "complete"}

    def datasets_create_version(self, owner, slug, version_note=None):
        self.calls.append(("datasets_create_version", owner, slug, version_note))
        return {"ref": f"{owner}/{slug}"}

    def kernels_push(self, path, **kwargs):
        self.calls.append(("kernels_push", path))
        self.pushed.append((path, kwargs))
        return {"ref": path}

async def test_legacy_bump_api_branch(kaggle_env, seed_job, monkeypatch):
    # hasattr dispatch: no dataset_create_version → datasets_create_version(owner, slug)
    legacy = LegacyStubKaggleApi()
    monkeypatch.setattr(orch, "_api", lambda: legacy)
    assert await orch.ensure_worker(SessionLocal) is True
    assert legacy.calls[0][:3] == (
        "datasets_create_version",
        "testuser",
        "img2text-worker-files",
    )
    assert legacy.calls[0][3].startswith("orchestrator spawn ")
    assert legacy.calls[1] == (
        "kernels_push",
        str(settings.kaggle_stage_dir),
    )  # order bump → push kept


async def test_datasets_bump_failure_blocks_spawn(kaggle_env, seed_job):
    # P2: stale-code guard — bump fail → warning + NO kernels_push
    StubKaggleApi.bump_error = RuntimeError("dataset missing")
    assert await orch.ensure_worker(SessionLocal) is False
    assert _api().pushed == []
    assert [c[0] for c in _api().calls] == ["dataset_create_version"]


async def test_skip_when_kernel_running(kaggle_env, seed_job):
    StubKaggleApi.status_result = "running"
    assert await orch.ensure_worker(SessionLocal) is False
    assert _api().pushed == []


async def test_skip_when_queue_empty(kaggle_env):
    assert await orch.ensure_worker(SessionLocal) is False
    assert _api().pushed == []


async def test_disabled_skips_without_kaggle_import(monkeypatch):
    # defaults: kaggle_username/key/kernel_ref all "" → kaggle_enabled False
    assert settings.kaggle_enabled is False
    real_import = builtins.__import__
    imported: list = []

    def spy(name, *args, **kwargs):
        if name.startswith("kaggle"):
            imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", spy)
    assert await orch.ensure_worker(SessionLocal) is False
    assert imported == []
    assert StubKaggleApi.instances == []

def test_enabled_credential_matrix(monkeypatch):
    # kaggle 2.x: KAGGLE_API_TOKEN replaces legacy KAGGLE_KEY; username
    # (OWNER metadata id) + kernel_ref stay required either way.
    monkeypatch.setattr(settings, "kaggle_username", "testuser")
    monkeypatch.setattr(settings, "kaggle_kernel_ref", "testuser/img2text-worker")
    monkeypatch.setattr(settings, "kaggle_api_token", "")
    monkeypatch.setattr(settings, "kaggle_key", "testkey")
    assert settings.kaggle_enabled is True  # legacy key only
    monkeypatch.setattr(settings, "kaggle_key", "")
    monkeypatch.setattr(settings, "kaggle_api_token", "KGAT_x")
    assert settings.kaggle_enabled is True  # token only (kaggle 2.x primary)
    monkeypatch.setattr(settings, "kaggle_api_token", "")
    assert settings.kaggle_enabled is False  # no creds → feature off


async def test_push_error_returns_false_logs_warning(
    kaggle_env, seed_job, caplog
):
    StubKaggleApi.push_error = RuntimeError("kaggle down")
    with caplog.at_level("WARNING", logger="app.services.kaggle_orchestrator"):
        assert await orch.ensure_worker(SessionLocal) is False
    assert any("kaggle" in r.message.lower() for r in caplog.records)


async def test_stage_kernel_substitutes_owner_ref_accelerator(
    kaggle_env, monkeypatch
):
    monkeypatch.setattr(settings, "kaggle_kernel_ref", "someone/img2text-worker")
    monkeypatch.setattr(settings, "kaggle_accelerator", "NvidiaTeslaP100")
    stage_dir = orch._stage_kernel()
    assert stage_dir == Path(settings.kaggle_stage_dir)
    # P1: committed ipynb snapshot copied (valid code_file; mount path fixed in 21f2ebc)
    nb = json.loads((stage_dir / "img2text_worker.ipynb").read_text(encoding="utf-8"))
    nb_src = "".join("".join(c.get("source", [])) for c in nb["cells"])
    assert '/kaggle/input/img2text-worker-files' in nb_src
    meta_text = (stage_dir / "kernel-metadata.json").read_text(encoding="utf-8")
    meta = json.loads(meta_text)
    # OWNER substituted + kernel_ref slug + username owner + accelerator
    assert "OWNER" not in meta_text
    assert meta["id"] == "testuser/img2text-worker"
    assert meta["dataset_sources"] == ["testuser/img2text-worker-files"]
    assert meta["accelerator"] == "NvidiaTeslaP100"
    assert meta["machine_shape"] == "NvidiaTeslaP100"
    assert meta["enable_gpu"] is True and meta["enable_internet"] is True
    for name in (
        "pipeline.py",
        "verdict.py",
        "dataset-metadata.json",
        "img2text_worker.ipynb",
    ):
        assert (stage_dir / name).is_file(), name
    # staged dataset-metadata.json carries the id the version bump needs (kaggle 2.2.4)
    ds_meta = json.loads((stage_dir / "dataset-metadata.json").read_text())
    assert ds_meta["id"] == "testuser/img2text-worker-files"
    # kaggle 2.2.4 metadata shape: title + id + licenses as dicts
    assert ds_meta["title"] == "img2text-worker-files"
    assert ds_meta["licenses"] == [{"name": "CC0-1.0"}]
    # source templates untouched (deploy/kaggle not modified)
    template = (DEPLOY_KAGGLE / "kernel" / "kernel-metadata.json").read_text(
        encoding="utf-8"
    )
    assert "OWNER" in template and "testuser" not in template


def test_normalize_licenses_old_string_shape():
    # defensive: old-shape ["CC0-1.0"] → [{"name": "CC0-1.0"}] (kaggle 2.2.4)
    assert orch._normalize_licenses(["CC0-1.0"]) == [{"name": "CC0-1.0"}]
    assert orch._normalize_licenses([{"name": "CC0-1.0"}]) == [
        {"name": "CC0-1.0"}
    ]

async def test_scheduler_reap_job_calls_ensure_worker(app, monkeypatch):
    from app.services.scheduler import init_scheduler

    mock = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.scheduler.ensure_worker", mock)
    scheduler = init_scheduler(app)
    job = scheduler.get_job("reap-leases")
    assert job is not None
    await job.func()
    assert mock.await_count == 1
    assert mock.await_args.args[0] is app.state.session_factory


async def test_gap_guard_blocks_second_spawn(kaggle_env, seed_job):
    # no sleep: real monotonic clock, gap default 600s — second call skips
    assert await orch.ensure_worker(SessionLocal) is True
    assert await orch.ensure_worker(SessionLocal) is False
    assert len(_pushed()) == 1

def test_input_url_expiry_reduced():
    """P2 #19 (spec 2026-10-16): manifest input_url window 3600 → 900s, configurable."""
    from app.core.config import settings
    assert settings.input_url_expires == 900
