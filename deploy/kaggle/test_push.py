import json
import sys
import types
from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEPLOY_DIR))

import push  # noqa: E402

KERNEL_REF = "alice/img2text-worker"
MOUNT_PATH = 'sys.path.insert(0, "/kaggle/input/img2text-worker-files")'

class _CoreApi:
    """Shared bookkeeping — subclasses expose ONE API generation of names
    so kcompat dispatch (new vs legacy) is exercised end-to-end."""

    def __init__(self):
        self.dataset_create_calls = []   # dataset id read from staged metadata
        self.dataset_version_calls = []  # (dataset id, version notes)
        self.kernel_push_calls = []
        self.kernel_status_calls = []

    def authenticate(self):
        pass

    def _create(self, folder):
        meta = json.loads((Path(folder) / "dataset-metadata.json").read_text())
        self.dataset_create_calls.append(meta["id"])

    def _bump(self, folder, notes):
        meta = json.loads((Path(folder) / "dataset-metadata.json").read_text())
        self.dataset_version_calls.append((meta["id"], notes))

    def kernels_push(self, kernel_path, **kwargs):
        built_meta = (Path(kernel_path) / "kernel-metadata.json").read_text()
        self.kernel_push_calls.append((kernel_path, kwargs, built_meta))

    def kernels_status(self, ref):
        self.kernel_status_calls.append(ref)
        return {"status": "complete"}

class FakeApi(_CoreApi):
    """kaggle 2.2.4 method names (the real package installed)."""

    def dataset_create_new(self, folder, **kwargs):
        self._create(folder)

    def dataset_create_version(self, folder, version_notes=""):
        self._bump(folder, version_notes)

class LegacyFakeApi(_CoreApi):
    """Pre-rename datasets_* names — kcompat legacy fallback branch."""

    def datasets_create_with_files(self, upload_folder=None, **kwargs):
        self._create(upload_folder)

    def datasets_create_version(self, owner, slug, version_note=""):
        # legacy call gets NO folder — record the ref kcompat split
        self.dataset_version_calls.append((f"{owner}/{slug}", version_note))

def _install(monkeypatch, api):
    module = types.ModuleType("kaggle")
    module.KaggleApi = lambda: api
    monkeypatch.setitem(sys.modules, "kaggle", module)
    monkeypatch.setenv("KAGGLE_USERNAME", "alice")
    monkeypatch.setenv("KAGGLE_KEY", "k123")
    return api

@pytest.fixture(params=[FakeApi, LegacyFakeApi])
def fake_api(monkeypatch, request):
    return _install(monkeypatch, request.param())

def test_kernel_metadata_owner_substitution(tmp_path):
    out = tmp_path / "kernel-metadata.json"
    push.build_kernel_metadata("alice", "NvidiaTeslaT4", out)
    meta = json.loads(out.read_text())
    assert meta["id"] == KERNEL_REF
    assert meta["dataset_sources"] == ["alice/img2text-worker-files"]
    assert meta["enable_gpu"] is True
    assert meta["enable_internet"] is True
    assert meta["machine_shape"] == "NvidiaTeslaT4"
    assert meta["kernel_type"] == "notebook"
    assert meta["is_private"] is True
    tpl = json.loads((DEPLOY_DIR / "kernel" / "kernel-metadata.json").read_text())
    assert tpl["id"] == "OWNER/img2text-worker"
    assert tpl["dataset_sources"] == ["OWNER/img2text-worker-files"]

def test_dataset_metadata_owner_substitution(tmp_path):
    out = tmp_path / "dataset-metadata.json"
    push.build_dataset_metadata("alice", out)
    meta = json.loads(out.read_text())
    assert meta["id"] == "alice/img2text-worker-files"
    assert meta["title"] == "img2text-worker-files"
    # kaggle 2.2.4 shape: title + id (owner/slug) + licenses as dicts
    assert meta["licenses"] == [{"name": "CC0-1.0"}]
    tpl = json.loads((DEPLOY_DIR / "files" / "dataset-metadata.json").read_text())
    assert tpl["id"] == "OWNER/img2text-worker-files"
    assert tpl["title"] == "img2text-worker-files"
    assert tpl["licenses"] == [{"name": "CC0-1.0"}]

def test_build_dataset_metadata_coerces_string_licenses(tmp_path, monkeypatch):
    # old-shape template ("licenses": ["CC0-1.0"]) → coerced to dicts
    old = tmp_path / "files"
    old.mkdir()
    (old / "dataset-metadata.json").write_text(
        json.dumps({"title": "t", "licenses": ["CC0-1.0"]})
    )
    monkeypatch.setattr(push, "FILES_DIR", old)
    out = tmp_path / "out.json"
    push.build_dataset_metadata("alice", out)
    meta = json.loads(out.read_text())
    assert meta["id"] == "alice/img2text-worker-files"
    assert meta["licenses"] == [{"name": "CC0-1.0"}]

def test_missing_env(monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        push.main(["--skip-dataset"])
    assert "KAGGLE_USERNAME" in str(exc.value)

def test_skip_dataset(fake_api):
    push.main(["--skip-dataset"])
    assert fake_api.dataset_create_calls == []
    assert fake_api.dataset_version_calls == []
    assert len(fake_api.kernel_push_calls) == 1
    _path, _kwargs, built = fake_api.kernel_push_calls[0]
    assert "OWNER" not in built
    assert KERNEL_REF in built
    assert fake_api.kernel_status_calls == [KERNEL_REF]

def test_dataset_create_then_version_bump(fake_api):
    def boom(*args, **kwargs):
        raise RuntimeError("dataset already exists")

    # patch the create method OF THE ACTIVE API GENERATION
    name = (
        "dataset_create_new"
        if isinstance(fake_api, FakeApi)
        else "datasets_create_with_files"
    )
    setattr(fake_api, name, boom)
    push.main([])
    assert fake_api.dataset_create_calls == []
    # version bump receives the STAGED FOLDER (files + dataset-metadata.json)
    assert fake_api.dataset_version_calls == [
        ("alice/img2text-worker-files", "push.py manual")
    ]

def test_notebook_builder(tmp_path):
    out = tmp_path / "img2text_worker.ipynb"
    push.build_kernel_notebook(out)
    nb = json.loads(out.read_text())  # valid JSON / nbformat
    assert nb["nbformat"] == 4
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "UserSecretsClient" in src
    assert MOUNT_PATH in src
    assert "/kaggle/input/img2text-worker-files/worker" not in src
    assert 'sys.path.insert(0, "worker")' not in src
    assert "google.colab" not in src
    assert "Kaggle Secrets (Add-ons" in src
    assert "img2text worker — Kaggle GPU runner" in src
    assert "Colab GPU runner" not in src
    # smoke / init / loop logic identical to colab notebook
    orig = json.loads((push.WORKER_DIR / "colab_notebook.ipynb").read_text())
    orig_src = "\n".join("".join(c["source"]) for c in orig["cells"])
    for frag in ("PaddleOCRVL", "run_job(", "PIPELINE.predict(\"TA.jpg\")"):
        assert frag in orig_src and frag in src
