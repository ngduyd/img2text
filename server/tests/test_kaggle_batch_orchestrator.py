"""Plan K5 — batch orchestration: queued job → stage input → dataset
delete+create → push script kernel → poll → result.json ingest.

Kaggle never called live: a per-test stub replaces orch._api() (the K2 file
installs a sys.modules stub for its own tests; dispatch is covered on both
sides here + in test_kaggle_orchestrator.py). Storage is the moto driver
from the conftest app fixture, injected through the orch._get_storage seam.
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.models import Job
from app.core.schemas import ResultBody
from app.services import kaggle_orchestrator as orch

DEPLOY_KAGGLE = Path(__file__).parents[2] / "deploy" / "kaggle"

RESULT_DOC = {
    "source_pdf": "uploads/x.png",
    "dpi": 200,
    "pages": [
        {
            "page": 1,
            "image": "/tmp/pre/page_0001.png",
            "width": 800,
            "height": 600,
            "preprocess": {"skew_deg": 0.0, "shadow_removed": True, "resized": False},
            "blocks": [
                {"id": "p1_b0", "order": 0, "type": "doc_title",
                 "bbox": [10, 10, 400, 60], "text": "Báo cáo", "empty": False},
                {"id": "p1_b1", "order": 1, "type": "paragraph_title",
                 "bbox": [10, 70, 400, 100], "text": "Mục 1", "empty": False},
                {"id": "p1_b2", "order": 2, "type": "table",
                 "bbox": [10, 110, 400, 300],
                 "text": "<table><tr><td>1</td></tr></table>", "empty": False},
                {"id": "p1_b3", "order": 3, "type": "image",
                 "bbox": [10, 310, 400, 500], "text": "hình minh họa", "empty": False},
                {"id": "p1_b4", "order": 4, "type": "text",
                 "bbox": [10, 510, 400, 550], "text": "   ", "empty": True},
            ],
        },
        {
            "page": 2,
            "image": "/tmp/pre/page_0002.png",
            "width": None,
            "height": None,
            "preprocess": {},
            "blocks": [
                {"id": "p2_b0", "order": 0, "type": "text",
                 "bbox": [5, 5, 300, 40], "text": "Trang hai", "empty": False},
            ],
        },
    ],
}

class BatchStubKaggleApi:
    """Live-shaped KaggleApi: enum-like status, folder dataset APIs, output pull."""

    def __init__(self) -> None:
        self.calls: list = []  # (method, ...) in call order
        self.status = {"status": SimpleNamespace(name="COMPLETE")}
        self.dataset_items: list = []
        self.result_doc: dict | None = None

    def dataset_list(self, search=None):
        self.calls.append(("dataset_list", search))
        return self.dataset_items

    def dataset_delete(self, owner, slug, no_confirm=False):
        self.calls.append(("dataset_delete", f"{owner}/{slug}"))
        return True

    def dataset_create_new(self, folder):
        meta = json.loads((Path(folder) / "dataset-metadata.json").read_text())
        files = sorted(p.name for p in Path(folder).iterdir())
        self.calls.append(("dataset_create_new", meta["id"], files))
        return {"ref": meta["id"]}

    def kernels_push(self, path):
        meta = json.loads((Path(path) / "kernel-metadata.json").read_text())
        files = sorted(p.name for p in Path(path).iterdir())  # dir dies after push
        self.calls.append(("kernels_push", path, meta, files))
        return meta["id"]

    def kernels_status(self, ref):
        self.calls.append(("kernels_status", ref))
        return self.status

    def kernels_output(self, ref, path=None, quiet=False):
        self.calls.append(("kernels_output", ref, path))
        assert self.result_doc is not None, "kernels_output before test set result_doc"
        (Path(path) / "result.json").write_text(
            json.dumps(self.result_doc, ensure_ascii=False), encoding="utf-8"
        )
        return None

    # K2 surface (only touched by the mode=loop dispatch test)
    def dataset_create_version(self, folder, version_notes=None):
        self.calls.append(("dataset_create_version", folder))
        return {"folder": folder}

@pytest.fixture(autouse=True)
def _reset_batch_state(monkeypatch):
    monkeypatch.setattr(orch, "_last_spawn", 0.0)
    monkeypatch.setattr(orch, "_batch_runs", {})
    yield

@pytest.fixture
def api(monkeypatch):
    stub = BatchStubKaggleApi()
    monkeypatch.setattr(orch, "_api", lambda: stub)
    return stub

@pytest.fixture
def kaggle_batch_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "kaggle_mode", "batch")
    monkeypatch.setattr(settings, "kaggle_username", "testuser")
    monkeypatch.setattr(settings, "kaggle_key", "testkey")
    monkeypatch.setattr(settings, "kaggle_kernel_ref", "testuser/img2text-worker")
    monkeypatch.setattr(settings, "kaggle_stage_src", str(DEPLOY_KAGGLE))
    monkeypatch.setattr(settings, "kaggle_stage_dir", str(tmp_path / "kaggle-kernel"))
    return settings

@pytest.fixture
def storage_env(app, storage_spy, monkeypatch):
    """moto driver (spied) through the orchestrator's storage seam."""
    monkeypatch.setattr(orch, "_get_storage", lambda: app.state.storage)
    return storage_spy

def _pushes(api) -> list:
    return [c for c in api.calls if c[0] == "kernels_push"]

async def test_batch_happy_flow_spawn_then_complete_ingest(
    kaggle_batch_env, api, storage_env, seed_job, db_session
):
    api.result_doc = RESULT_DOC
    # tick 1: queued → stage input → dataset delete+create → push
    assert await orch.ensure_worker(SessionLocal) is True
    job = await db_session.get(Job, seed_job)
    assert job.storage_key.startswith("uploads/")
    storage_env.get.assert_awaited_with(job.storage_key)  # staged from storage
    creates = [c for c in api.calls if c[0] == "dataset_create_new"]
    assert creates[0][1] == "testuser/img2text-input"
    assert f"{job.storage_key.rsplit('/', 1)[-1]}" in creates[0][2]  # sha.<ext> staged
    assert "dataset-metadata.json" in creates[0][2]
    pushes = _pushes(api)
    assert len(pushes) == 1
    _method, _path, meta, files = pushes[0]
    assert meta["id"] == "testuser/img2text-batch"
    assert meta["dataset_sources"] == ["testuser/img2text-input"]  # input dataset ONLY
    assert meta["kernel_type"] == "script"
    assert meta["enable_gpu"] is True
    assert "img2text_batch.py" in files and "kernel-metadata.json" in files
    assert seed_job in orch._batch_runs
    # tick 2: enum-shaped status → complete → output pulled → ingest
    assert await orch.ensure_worker(SessionLocal) is False
    assert any(
        c[0] == "kernels_output" and c[1] == "testuser/img2text-batch"
        for c in api.calls
    )
    assert orch._batch_runs == {}
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done" and job.finished_at is not None
    assert job.worker_token is None and job.lease_expires_at is None
    res = job.result
    assert res["model_version"] == orch.BATCH_MODEL_VERSION
    assert res["gpu_seconds"] == 0.0
    assert res["warnings"] == []
    assert len(res["pages"]) == 2
    p1 = res["pages"][0]
    assert p1["index"] == 1 and p1["width"] == 800 and p1["height"] == 600
    # image + empty-text blocks dropped; doc_title/paragraph_title/table kept
    assert [r["text"] for r in p1["regions"]] == [
        "Báo cáo",
        "Mục 1",
        "<table><tr><td>1</td></tr></table>",
    ]
    assert all(
        set(r) == {"id", "bbox", "text", "verdict", "placeholder"}
        and r["verdict"] == "ok"
        and r["placeholder"] is False
        for r in p1["regions"]
    )
    assert p1["markdown"].startswith("# Báo cáo")
    assert "\n\n## Mục 1" in p1["markdown"]
    assert "<table><tr><td>1</td></tr></table>" in p1["markdown"]
    p2 = res["pages"][1]
    assert p2["index"] == 2 and p2["width"] == 0 and p2["height"] == 0
    assert p2["markdown"] == "Trang hai"
    assert res["markdown"] == p1["markdown"] + "\n\n---\n\n" + p2["markdown"]
    # validated against the exact worker result shape
    ResultBody.model_validate(res)

async def test_batch_preprocess_ceiling_warns_and_ingests_whole_file(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog
):
    api.result_doc = RESULT_DOC
    job = await db_session.get(Job, seed_job)
    job.preprocess = '{"pages": [1], "rotate": {"1": 90}}'
    await db_session.commit()
    assert await orch.ensure_worker(SessionLocal) is True  # spawn
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False  # complete → ingest
    assert any("bỏ qua preprocess" in r.getMessage() for r in caplog.records)
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"
    assert len(job.result["pages"]) == 2  # whole file, selection ignored

async def test_batch_failed_drops_ref_and_respawns_after_gap(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog, monkeypatch
):
    assert await orch.ensure_worker(SessionLocal) is True
    api.status = {"status": SimpleNamespace(name="FAILED")}
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False  # poll drops ref
    assert orch._batch_runs == {}  # ref deleted
    assert any("stays queued" in r.getMessage() for r in caplog.records)
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "queued"  # job untouched → respawn candidate
    # gap guard still blocks (default 600s since first spawn)
    assert await orch.ensure_worker(SessionLocal) is False
    assert len(_pushes(api)) == 1
    # gap elapsed → respawn next tick
    monkeypatch.setattr(settings, "kaggle_min_gap_seconds", 0)
    assert await orch.ensure_worker(SessionLocal) is True
    assert len(_pushes(api)) == 2
    assert seed_job in orch._batch_runs

async def test_batch_timeout_drops_ref_with_warning(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog
):
    assert await orch.ensure_worker(SessionLocal) is True
    run = orch._batch_runs[seed_job]
    run["pushed_at"] = time.monotonic() - settings.kaggle_timeout - 1
    api.status = {"status": SimpleNamespace(name="RUNNING")}
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False
    assert orch._batch_runs == {}
    assert any("kaggle_timeout" in r.getMessage() for r in caplog.records)
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "queued"

async def test_mode_loop_dispatches_to_k2_branch(
    kaggle_batch_env, api, storage_env, seed_job, monkeypatch
):
    monkeypatch.setattr(settings, "kaggle_mode", "loop")
    batch = AsyncMock(return_value=True)
    monkeypatch.setattr(orch, "_ensure_batch_runs", batch)
    # K2 path: status check → queue → gap → stage worker kernel → bump → push
    api.status = {"status": "complete"}
    assert await orch.ensure_worker(SessionLocal) is True
    batch.assert_not_awaited()
    kinds = [c[0] for c in api.calls]
    assert "dataset_create_version" in kinds and "kernels_push" in kinds
    assert "dataset_create_new" not in kinds  # batch staging untouched

async def test_mode_batch_dispatches_to_batch_branch(
    kaggle_batch_env, api, storage_env, monkeypatch
):
    batch = AsyncMock(return_value=True)
    monkeypatch.setattr(orch, "_ensure_batch_runs", batch)
    assert await orch.ensure_worker(SessionLocal) is True
    batch.assert_awaited_once()

# --- adapter unit cases (pure, no DB) ---

def test_adapter_drops_image_and_empty_keeps_table_html():
    out = orch.adapt_batch_document(RESULT_DOC)
    body = ResultBody.model_validate(out)
    p1 = body.pages[0]
    texts = [r.text for r in p1.regions]
    assert "hình minh họa" not in texts  # type=="image" dropped (even with text)
    assert not any(t.strip() == "" for t in texts)  # empty text dropped
    assert "<table><tr><td>1</td></tr></table>" in texts  # HTML kept verbatim
    assert p1.markdown.startswith("# Báo cáo")
    assert p1.markdown.splitlines()[2].startswith("## Mục 1")

def test_adapter_title_prefixes_and_page_join():
    out = orch.adapt_batch_document(RESULT_DOC)
    assert out["markdown"].count("\n\n---\n\n") == 1  # 2 pages, one separator
    assert out["pages"][0]["markdown"].split("\n\n")[0] == "# Báo cáo"
    # bbox passthrough, verdict/placeholder batch defaults
    assert out["pages"][0]["regions"][0]["bbox"] == [10, 10, 400, 60]
    assert out["pages"][1]["regions"][0]["verdict"] == "ok"
    assert out["gpu_seconds"] == 0.0  # ceiling: wall time not tracked

def test_adapter_missing_dimensions_default_zero():
    doc = {"pages": [{"page": 1, "blocks": [
        {"id": "b", "type": "text", "bbox": None, "text": "x"}]}]}
    page = orch.adapt_batch_document(doc)["pages"][0]
    assert page["width"] == 0 and page["height"] == 0
    assert page["index"] == 1 and page["regions"][0]["bbox"] is None

def test_norm_status_enum_and_string_forms():
    assert orch._norm_status({"status": SimpleNamespace(name="COMPLETE")}) == "complete"
    assert orch._norm_status({"status": "KernelWorkerStatus.FAILED"}) == "failed"
    assert orch._norm_status({"status": "running"}) == "running"
    assert orch._norm_status({"status": None}) is None
