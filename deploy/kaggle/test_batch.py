"""Batch mode tests (Plan K4) — mock kaggle via sys.modules, NO network.

Covers: standalone single-file script contract (img2text_batch.py) +
run_one staging (script + batch metadata + input dataset ONLY). Tests for
the removed img2text_batch.ipynb notebook contract were deleted with the
notebook (they tested a deleted artifact).
"""
import json
import os
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
BATCH_SCRIPT = DEPLOY_DIR / "kernel" / "img2text_batch.py"
BATCH_META_TPL = DEPLOY_DIR / "kernel" / "kernel-batch-metadata.json"

# kaggle 2.2.4 LIVE status shape: enum-repr strings (was: circular lowercase mock)
_RUNNING = "KernelWorkerStatus.RUNNING"
_COMPLETE = "KernelWorkerStatus.COMPLETE"
_FAILED = "KernelWorkerStatus.FAILED"

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
        self.statuses = [_COMPLETE]

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

def test_missing_env(monkeypatch, input_file):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file)])
    assert "KAGGLE_USERNAME" in str(exc.value)

def test_directory_input_rejected(fake_api, tmp_path):
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(tmp_path)])
    assert "1 file" in str(exc.value)

def test_no_worker_files_dataset(fake_api, input_file):
    # K4: worker-files dataset dropped — the .py script IS the worker.
    # run 1: input new → create; run 2: input exists → delete+recreate.
    assert not hasattr(run_one, "stage_worker")
    run_one.main([str(input_file)])
    assert [ref for ref, _ in fake_api.create_calls] == [INPUT_REF]
    assert fake_api.delete_calls == []
    run_one.main([str(input_file)])
    assert fake_api.delete_calls == [INPUT_REF]
    assert [ref for ref, _ in fake_api.create_calls] == [INPUT_REF, INPUT_REF]
    # ONLY the input dataset is ever touched — no worker-files create call
    assert all(ref == INPUT_REF for ref, _ in fake_api.create_calls)

def test_exists_check_uses_dataset_list_method(fake_api, input_file):
    # the exists path must call a REAL list method — never a swallowed
    # AttributeError from the renamed create API
    run_one.main([str(input_file)])
    # dataset_list(search=slug) — real method, no owner prefix in search
    assert fake_api.list_calls == ["img2text-input"]

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
    # script kernel, input dataset ONLY (worker code lives in the .py)
    assert meta["dataset_sources"] == [INPUT_REF, "jhandf/img2text-wheelbuild-env"]  # input + wheelhouse
    assert meta["kernel_type"] == "script"
    assert meta["enable_gpu"] is True
    assert meta["enable_internet"] is True
    assert meta["machine_shape"] == "NvidiaTeslaT4"
    assert meta["accelerator"] == "NvidiaTeslaT4"
    assert meta["code_file"] == "img2text_batch.py"
    assert "img2text_batch.py" in names and "kernel-metadata.json" in names
    assert not any(n.endswith(".ipynb") for n in names)   # script kernel, no notebook

def test_batch_metadata_template_shape():
    tpl = json.loads(BATCH_META_TPL.read_text(encoding="utf-8"))
    assert tpl["id"] == "OWNER/img2text-batch"
    assert tpl["code_file"] == "img2text_batch.py"
    assert tpl["language"] == "python"
    assert tpl["kernel_type"] == "script"
    assert tpl["is_private"] is True
    assert tpl["enable_gpu"] is True
    assert tpl["enable_internet"] is True
    assert tpl["machine_shape"] == "NvidiaTeslaT4"
    assert tpl["dataset_sources"] == ["OWNER/img2text-input", "jhandf/img2text-wheelbuild-env"]

def test_status_loop_running_then_complete(fake_api, input_file, monkeypatch):
    fake_api.statuses = [_RUNNING, _RUNNING, _COMPLETE]
    sleeps = []
    monkeypatch.setattr(run_one, "SLEEP", sleeps.append)
    run_one.main([str(input_file), "--poll", "20"])
    assert fake_api.status_calls == [KERNEL_REF] * 3
    assert sleeps == [20, 20]

def test_failed_exits_1(fake_api, input_file):
    fake_api.statuses = [_FAILED]
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file)])
    assert exc.value.code == 1

def test_timeout_exits_2(fake_api, input_file):
    fake_api.statuses = [_RUNNING]
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file), "--poll", "20", "--timeout", "40"])
    assert exc.value.code == 2
    assert fake_api.status_calls == [KERNEL_REF] * 3  # elapsed 0, 20, 40

def test_enum_object_status_stops_loop(fake_api, input_file):
    # status value as enum-name OBJECT (SimpleNamespace with .name) → 'complete'
    fake_api.statuses = [types.SimpleNamespace(name="COMPLETE")]
    run_one.main([str(input_file)])  # returns (no SystemExit) on FIRST poll
    assert fake_api.status_calls == [KERNEL_REF]
    assert len(fake_api.output_calls) == 1  # pull_output ran next in flow

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
    fake_api.statuses = [_RUNNING]
    sleeps = []
    monkeypatch.setattr(run_one, "SLEEP", sleeps.append)
    with pytest.raises(SystemExit) as exc:
        run_one.main([str(input_file), "--poll", "0", "--timeout", "4"])
    assert exc.value.code == 2          # bounded loop, no busy-spin
    assert sleeps == [1, 1, 1, 1]       # clamped to 1s

def test_script_compiles():
    compile(BATCH_SCRIPT.read_text(encoding="utf-8"), str(BATCH_SCRIPT), "exec")

def test_script_contract():
    """Standalone single-file batch kernel (Plan K4 + py3.12 venv amendment)."""
    src = BATCH_SCRIPT.read_text(encoding="utf-8")
    low = src.lower()
    # py3.12 venv recipe (user-proven — VLM_OCR_pipeline(2) cell 5)
    assert '"uv", "venv"' in src              # uv venv <dir>
    assert '"--python", "3.12"' in src        # separate py3.12 (kaggle 3.13 has no paddle)
    assert "paddlepaddle-gpu==3.2.1" in src
    assert "https://www.paddlepaddle.org.cn/packages/stable/cu126/" in src
    assert 'paddleocr[doc-parser]>=3.6.0' in src
    assert "if not os.path.exists(VENV_PY)" in src   # idempotent: skip recreate
    assert "venv py3.12/paddle không cài được" in src  # clear SystemExit hint
    # --ocr re-exec: parent re-runs THIS file under the venv python
    assert '"--ocr"' in src and "VENV_PY" in src
    assert 'sys.argv[1] == "--ocr"' in src
    # light kernel-python deps only (no httpx/pypdf — no server loop, pdf via pdftoppm)
    assert "httpx" not in low and "pypdf" not in low
    assert "poppler-utils" in src and "pdftoppm" in src   # apt kept, NOT PyMuPDF
    assert "fitz" not in low and "pymupdf" not in low
    # recursive input discovery (new mount: /kaggle/input/<owner>/<slug>/)
    assert '"/kaggle/input/**/*"' in src and "recursive=True" in src
    # standalone: no cross-import, no sys.path mount, no worker-files dataset
    assert "from pipeline import" not in src
    assert "from verdict import" not in src
    assert "sys.path.insert" not in src
    assert "img2text-worker-files" not in src
    # flattened pieces: verdict (full) + needed pipeline helpers + preprocess
    for frag in ("def precheck", "def resolve", "class Region", "class PrecheckResult",
                 "def default_pdftoppm", "def estimate_skew", "def remove_shadow",
                 "def extract_blocks", "def run_ocr", "def find_input"):
        assert frag in src, frag
    # cell-14 normalize shape → result.json, result.md output
    assert "block_bbox" in src and "block_content" in src and "block_label" in src
    assert 'f"p{page_no}_b{i}"' in src
    # output capture: /kaggle/working = script-kernel capture (platform),
    # /kaggle/outputs = notebook-compat copy — both via _write_outputs
    assert '"/kaggle/working"' in src
    assert '"/kaggle/outputs"' in src
    assert "def _write_outputs" in src
    assert '"result.json"' in src and '"result.md"' in src
    # pinned PaddleOCRVL init (notebook user-proven flags)
    assert 'pipeline_version=PIPELINE_VERSION' in src
    assert 'VL_MODEL = "PaddleOCR-VL-1.5-0.9B"' in src
    assert 'LAYOUT_MODEL = "PP-DocLayoutV3"' in src
    assert "use_doc_orientation_classify=True" in src
    assert "use_doc_unwarping=True" in src
    # no backend/secrets coupling anywhere
    for banned in ("RUNNER_KEY", "BASE_URL", "usersecrets"):
        assert banned.lower() not in low

def test_wheelhouse_deps_include_rembg():
    """WS-PIPE P0: venv wheelhouse phải cài rembg — thiếu → extract_crops
    ImportError → crops={} im im."""
    src = BATCH_SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"WHEELHOUSE_DEPS = \[(.*?)\]", src, re.S)
    assert m and '"rembg"' in m.group(1)
    assert "import paddle, paddleocr, rembg" in src  # repair/verify check

def test_script_module_docstring_ceiling():
    doc = BATCH_SCRIPT.read_text(encoding="utf-8").lstrip('"')
    head = doc.split('"""')[0]
    assert "Standalone" in head
    assert "3.12" in head          # venv ceiling documented

def _load_script_funcs(names, ns):
    """AST-extract selected top-level defs — no bootstrap/network on import."""
    import ast
    tree = ast.parse(BATCH_SCRIPT.read_text(encoding="utf-8"))
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(keep) == len(names)
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(BATCH_SCRIPT), "exec"), ns)

def test_extract_blocks_cell14_shape():
    ns = {"os": os, "json": json}
    _load_script_funcs({"extract_blocks"}, ns)
    raw = {"res": {"parsing_res_list": [
        {"block_bbox": [1.2, 2.7, 3.0, 4.6], "block_content": "xin chào", "block_label": "text"},
        {"block_bbox": None, "block_content": " ", "block_label": "table"},
    ]}}
    blocks = ns["extract_blocks"](raw, 3)
    assert blocks[0] == {"id": "p3_b0", "order": 0, "type": "text",
                         "bbox": [1, 3, 3, 5], "text": "xin chào", "empty": False}
    assert blocks[1]["id"] == "p3_b1" and blocks[1]["bbox"] is None
    assert blocks[1]["empty"] is True and blocks[1]["type"] == "table"

def test_normalize_gated_and_missing_pages(tmp_path):
    ns = {"os": os, "json": json}
    _load_script_funcs({"extract_blocks", "normalize"}, ns)
    raw_dir, pre_dir = tmp_path / "raw", tmp_path / "pre"
    raw_dir.mkdir(); pre_dir.mkdir()
    # page 1: OCR ok → blocks from raw JSON, image = preprocessed path
    (raw_dir / "page_0001.json").write_text(json.dumps(
        {"res": {"parsing_res_list": [{"block_bbox": [0, 0, 10, 10],
                                        "block_content": "abc", "block_label": "text"}],
                 "width": 100, "height": 50}}), encoding="utf-8")
    (pre_dir / "page_0001.png").write_bytes(b"x")
    # page 2: gated by precheck (blurry+small) — no pre file, no raw JSON
    raw_paths = [str(raw_dir / "page_0001.png"), str(raw_dir / "page_0002.png")]
    pre_info = {
        "page_0001.png": {"width": 100, "height": 50, "skew_deg": 0.0,
                          "shadow_removed": True, "resized": False},
        "page_0002.png": {"width": 50, "height": 40, "gated": True},
    }
    pages, problems = ns["normalize"](raw_paths, pre_info, str(raw_dir), str(pre_dir))
    assert [p["page"] for p in pages] == [1, 2]
    assert pages[0]["image"] == str(pre_dir / "page_0001.png")
    assert pages[0]["preprocess"] == {"skew_deg": 0.0, "shadow_removed": True,
                                      "resized": False}
    assert pages[0]["blocks"][0]["text"] == "abc"
    # gated page stays present: raw image path, no preprocess keys, blocks []
    assert pages[1]["image"] == str(raw_dir / "page_0002.png")
    assert pages[1]["preprocess"] == {}
    assert pages[1]["blocks"] == []
    assert pages[1]["width"] == 50 and pages[1]["height"] == 40
    assert any("precheck unreadable" in m for m in problems)
