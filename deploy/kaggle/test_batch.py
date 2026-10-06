"""Batch mode tests (Plan K3) — mock kaggle via sys.modules, NO network."""
import json
import sys
import types
from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEPLOY_DIR))

import run_one  # noqa: E402

OWNER = "alice"
KERNEL_REF = "alice/img2text-batch"
INPUT_REF = "alice/img2text-input"
WORKER_REF = "alice/img2text-worker-files"
BATCH_NB = DEPLOY_DIR / "kernel" / "img2text_batch.ipynb"


class FakeApi:
    def __init__(self):
        self.created = set()
        self.create_calls = []
        self.version_calls = []
        self.kernel_push_calls = []
        self.status_calls = []
        self.output_calls = []
        self.statuses = ["complete"]

    def authenticate(self):
        pass

    def datasets_create_with_files(self, upload_folder=None, **kwargs):
        meta = json.loads((Path(upload_folder) / "dataset-metadata.json").read_text())
        ref = meta["id"]
        self.create_calls.append(ref)
        if ref in self.created:
            raise RuntimeError("dataset already exists")
        self.created.add(ref)

    def datasets_create_version(self, ref, version_note="", **kwargs):
        self.version_calls.append(ref)

    def kernels_push(self, folder, **kwargs):
        stage = Path(folder)
        built = (stage / "kernel-metadata.json").read_text()
        names = sorted(p.name for p in stage.iterdir())
        self.kernel_push_calls.append((built, names))

    def kernels_status(self, ref):
        self.status_calls.append(ref)
        idx = min(len(self.status_calls) - 1, len(self.statuses) - 1)
        return {"status": self.statuses[idx]}

    def kernels_output(self, ref, path=None, quiet=None, **kwargs):
        self.output_calls.append((ref, path, quiet))


@pytest.fixture
def fake_api(monkeypatch):
    api = FakeApi()
    module = types.ModuleType("kaggle")
    module.KaggleApi = lambda: api
    monkeypatch.setitem(sys.modules, "kaggle", module)
    monkeypatch.setenv("KAGGLE_USERNAME", OWNER)
    monkeypatch.setenv("KAGGLE_KEY", "k123")
    monkeypatch.setattr(run_one, "SLEEP", lambda s: None)
    return api


@pytest.fixture
def input_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "a.jpg"
    f.write_bytes(b"\xff\xd8fakejpg")
    return f


def test_missing_env(monkeypatch, input_file):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file)])
    assert "KAGGLE_USERNAME" in str(exc.value)


def test_directory_input_rejected(fake_api, tmp_path):
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(tmp_path)])
    assert "1 file" in str(exc.value)


def test_dataset_create_then_version(fake_api, input_file):
    # run 1: both datasets new → create
    run_one.main([str(input_file)])
    assert fake_api.create_calls == [WORKER_REF, INPUT_REF]
    assert fake_api.version_calls == []
    # run 2: both exist → version bump, input ref exact
    run_one.main([str(input_file)])
    assert fake_api.version_calls == [WORKER_REF, INPUT_REF]
    # staged input dataset metadata: title img2text-input (via create ref/id)
    assert INPUT_REF in fake_api.create_calls


def test_kernel_metadata_contents(fake_api, input_file):
    run_one.main([str(input_file)])
    built, names = fake_api.kernel_push_calls[0]
    meta = json.loads(built)
    assert "OWNER" not in built
    assert meta["id"] == KERNEL_REF
    assert meta["dataset_sources"] == [WORKER_REF, INPUT_REF]
    assert meta["kernel_type"] == "notebook"
    assert meta["enable_gpu"] is True
    assert meta["enable_internet"] is True
    assert meta["machine_shape"] == "NvidiaTeslaT4"
    assert meta["accelerator"] == "NvidiaTeslaT4"
    assert meta["code_file"] == "img2text_batch.ipynb"
    assert "img2text_batch.ipynb" in names and "kernel-metadata.json" in names


def test_status_loop_running_then_complete(fake_api, input_file, monkeypatch):
    fake_api.statuses = ["running", "running", "complete"]
    sleeps = []
    monkeypatch.setattr(run_one, "SLEEP", sleeps.append)
    run_one.main([str(input_file), "--poll", "20"])
    assert fake_api.status_calls == [KERNEL_REF] * 3
    assert sleeps == [20, 20]


def test_failed_exits_1(fake_api, input_file):
    fake_api.statuses = ["failed"]
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file)])
    assert exc.value.code == 1


def test_timeout_exits_2(fake_api, input_file):
    fake_api.statuses = ["running"]
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file), "--poll", "20", "--timeout", "40"])
    assert exc.value.code == 2
    assert fake_api.status_calls == [KERNEL_REF] * 3  # elapsed 0, 20, 40


def test_kernels_output_called_with_out_path(fake_api, input_file):
    run_one.main([str(input_file), "--out", "./out"])
    assert len(fake_api.output_calls) == 1
    ref, path, quiet = fake_api.output_calls[0]
    assert ref == KERNEL_REF
    assert quiet is False
    out = Path(path)
    assert out.parent == Path("out") and out.is_dir()


def test_batch_notebook_contract():
    nb = json.loads(BATCH_NB.read_text(encoding="utf-8"))  # valid JSON / nbformat
    assert nb["nbformat"] == 4
    assert len(nb["cells"]) == 4
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    low = src.lower()
    # input read + worker mount + output writes
    assert "/kaggle/input/img2text-input/" in src
    assert 'sys.path.insert(0, "/kaggle/input/img2text-worker-files/worker")' in src
    assert "/kaggle/outputs/result.json" in src
    assert "/kaggle/outputs/result.md" in src
    # no backend/secrets coupling anywhere
    for banned in ("RUNNER_KEY", "BASE_URL", "usersecrets"):
        assert banned.lower() not in low
    # setup mirrors existing notebook + pinned PaddleOCRVL init
    assert "!apt-get -qq install -y poppler-utils" in src
    assert "!pip install -q paddlepaddle-gpu paddleocr httpx" in src
    for frag in (
        'pipeline_version="v1.5"',
        'vl_rec_model_name="PaddleOCR-VL-1.5-0.9B"',
        'layout_detection_model_name="PP-DocLayoutV3"',
        "raise SystemExit(1)",
    ):
        assert frag in src
    # reuses pipeline helpers (no duplicated OCR logic)
    for frag in ("default_pdftoppm", "precheck", "build_page", "build_result"):
        assert f"from pipeline import" in src and frag in src
