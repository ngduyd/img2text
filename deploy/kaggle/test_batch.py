"""Batch mode tests (Plan K3) — mock kaggle via sys.modules, NO network."""
import json
import re
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


class _CoreApi:
    """Shared bookkeeping — subclasses expose ONE API generation of names;
    the parametrized fake_api fixture runs every test on both shapes."""

    def __init__(self):
        self.created = set()
        self.create_calls = []   # (ref, {filename: bytes}) snapshot at call time
        self.delete_calls = []
        self.list_calls = []     # search= args: the exists check, real method
        self.kernel_push_calls = []
        self.status_calls = []
        self.output_calls = []
        self.statuses = ["complete"]

    def authenticate(self):
        pass

    def _list(self, search=None):
        self.list_calls.append(search)
        return [{"ref": ref} for ref in sorted(self.created)]

    def _create(self, upload_folder):
        stage = Path(upload_folder)
        meta = json.loads((stage / "dataset-metadata.json").read_text())
        ref = meta["id"]
        files = {
            p.name: p.read_bytes()
            for p in stage.iterdir()
            if p.is_file() and p.name != "dataset-metadata.json"
        }
        self.create_calls.append((ref, files))
        if ref in self.created:
            raise RuntimeError("dataset already exists")
        self.created.add(ref)

    def _delete(self, ref):
        self.delete_calls.append(ref)
        self.created.discard(ref)
        return True

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

class FakeApi(_CoreApi):
    """kaggle 2.2.4 method names (the real package installed)."""

    def dataset_create_new(self, folder, **kwargs):
        self._create(folder)

    def dataset_delete(self, owner_slug, dataset_slug, no_confirm=False):
        return self._delete(f"{owner_slug}/{dataset_slug}")

    def dataset_list(self, search=None, **kwargs):
        return self._list(search)

class LegacyFakeApi(_CoreApi):
    """Pre-rename datasets_* names — kcompat legacy fallback branch."""

    def datasets_create_with_files(self, upload_folder=None, **kwargs):
        self._create(upload_folder)

    def datasets_delete(self, ref):
        return self._delete(ref)

    def dataset_list(self, search=None, **kwargs):
        return self._list(search)

@pytest.fixture(params=[FakeApi, LegacyFakeApi])
def fake_api(monkeypatch, request):
    api = request.param()
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


def test_dataset_meta_shape_kaggle_224(tmp_path):
    # kaggle 2.2.4: {title, id owner/slug, licenses:[{name}]} — old string
    # licenses → create fails "Key name not found in data"
    src = tmp_path / "a.jpg"
    src.write_bytes(b"\xff\xd8fakejpg")
    run_one.stage_input(src, OWNER, tmp_path / "in")
    in_meta = json.loads((tmp_path / "in" / "dataset-metadata.json").read_text())
    assert in_meta == {
        "id": INPUT_REF,
        "title": "img2text-input",
        "licenses": [{"name": "CC0-1.0"}],
    }
    run_one.stage_worker(OWNER, tmp_path / "wk")
    wk_meta = json.loads((tmp_path / "wk" / "dataset-metadata.json").read_text())
    assert wk_meta["id"] == WORKER_REF
    assert wk_meta["title"] == "img2text-worker-files"
    assert wk_meta["licenses"] == [{"name": "CC0-1.0"}]

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


def test_dataset_create_then_delete_recreate(fake_api, input_file):
    # run 1: both datasets new → exists check False → create (no delete)
    run_one.main([str(input_file)])
    assert [ref for ref, _ in fake_api.create_calls] == [WORKER_REF, INPUT_REF]
    assert fake_api.delete_calls == []
    # run 2: input exists → delete+recreate (worker kept — shared with K2)
    run_one.main([str(input_file)])
    assert fake_api.delete_calls == [INPUT_REF]
    assert [ref for ref, _ in fake_api.create_calls] == [
        WORKER_REF, INPUT_REF,   # run 1
        INPUT_REF,               # run 2: worker exists → kept, input recreated
    ]

def test_exists_check_uses_dataset_list_method(fake_api, input_file):
    # the exists path must call a REAL list method — never a swallowed
    # AttributeError from the renamed create API
    run_one.main([str(input_file)])
    # dataset_list(search=slug) — real method, no owner prefix in search
    assert fake_api.list_calls == [
        "img2text-worker-files",
        "img2text-input",
    ]

def test_exists_check_missing_method_fails_clearly(fake_api, input_file, monkeypatch):
    # hasattr check must fail → clear RuntimeError → SystemExit, no create
    monkeypatch.delattr(type(fake_api), "dataset_list")
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file)])
    assert "dataset_list" in str(exc.value)
    assert fake_api.create_calls == []


def test_second_run_uploads_fresh_input(fake_api, input_file):
    run_one.main([str(input_file)])
    file_b = input_file.parent / "b.jpg"
    file_b.write_bytes(b"CONTENT-B")
    file_b.replace(input_file)          # run 2 serves a different file
    run_one.main([str(input_file)])
    input_creates = [files for ref, files in fake_api.create_calls if ref == INPUT_REF]
    # 1st run: create with A; 2nd run: exists → delete + recreate with B
    assert len(input_creates) == 2
    assert input_creates[0]["a.jpg"] != b"CONTENT-B"   # run 1: file A
    assert input_creates[1]["a.jpg"] == b"CONTENT-B"   # run 2 recreate: file B
    assert INPUT_REF in fake_api.delete_calls


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
    # microsecond suffix → back-to-back runs never share an output dir
    assert re.fullmatch(r"\d{8}-\d{6}-\d{6}", out.name)


def test_poll_clamped_to_min_1(fake_api, input_file, monkeypatch):
    fake_api.statuses = ["running"]
    sleeps = []
    monkeypatch.setattr(run_one, "SLEEP", sleeps.append)
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file), "--poll", "0", "--timeout", "4"])
    assert exc.value.code == 2          # bounded loop, no busy-spin
    assert sleeps == [1, 1, 1, 1]       # clamped to 1s


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
