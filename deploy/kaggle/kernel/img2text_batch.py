"""Standalone Kaggle batch kernel (Plan K4) — ONE self-contained file.

kernel_type "script": pushed by deploy/kaggle/run_one.py — no worker-files
dataset, no sys.path mounts, no backend/secrets. Contains worker/verdict.py
(flattened, full) + the batch pieces of worker/pipeline.py + the proven flow
from VLM_OCR_pipeline(2).ipynb (cells 5/12/14).

Two phases, ONE file:
- parent phase (kernel Python, light deps): locate ALL staged inputs
  ({job_id}__ prefix) → rasterize (pdftoppm) → preprocess → precheck gate →
  re-exec self under the py3.12 venv for OCR → normalize raw JSON →
  {job_id}_result.{json,md} into /kaggle/working (script-kernel output
  capture) + copy to /kaggle/outputs (notebook compat).
- OCR phase: `img2text_batch.py --ocr <img_dir> <raw_dir>` runs under
  /tmp/paddle-venv/bin/python (PaddleOCR-VL loaded ONCE, resumable per-page).

Ceilings (ponytail):
- Kaggle default Python 3.13 has no paddle wheels → separate uv venv
  --python 3.12 (user-proven recipe). If venv creation fails: kiểm tra
  kernel internet=true + GPU quota (SystemExit message says so).
- Bootstrap (pip/apt/venv) runs only as __main__ — importing this module
  (unit tests) must stay cheap: no side effects, stdlib-only.
- Per-job OCR subprocess = model reload per job (venv/paddle install vẫn
  1 lần); upgrade path = gộp page của nhiều job vào 1 lần predict.
- result.json = notebook document shape (pages[]/blocks[]), NOT prod spec §4;
  page `image` paths point at the kernel tmp dir (not pulled back);
- result.md = plain join block-text mỗi trang — batch-grade, khác worker prod
  (bỏ image-block, không Cảnh-báo marker/page_flag). sync production sau.
"""
from __future__ import annotations
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

# ===========================================================================
# OCR phase — re-exec'd under /tmp/paddle-venv/bin/python (argv: --ocr img raw).
# Runs BEFORE any bootstrap/heavy import: the venv has paddleocr only.
# Mirrors VLM_OCR_pipeline(2).ipynb cell 12 (load model once, resumable).
# ===========================================================================

PIPELINE_VERSION = "v1.5"
VL_MODEL = "PaddleOCR-VL-1.5-0.9B"
LAYOUT_MODEL = "PP-DocLayoutV3"


def _ocr_phase(argv: list[str]) -> int:
    import traceback
    from pathlib import Path

    from paddleocr import PaddleOCRVL

    img_dir, raw_dir = Path(argv[0]), Path(argv[1])
    force = len(argv) > 2 and argv[2] == "1"

    def to_jsonable(o):
        if hasattr(o, "tolist"):
            return o.tolist()
        return str(o)

    pages = sorted(img_dir.glob("page_*.png"))
    todo = [p for p in pages if force or not (raw_dir / f"{p.stem}.json").exists()]
    print(f"[batch] {len(pages)} trang, cần chạy {len(todo)}", flush=True)
    if not todo:
        return 0

    t0 = time.time()
    pipeline = PaddleOCRVL(
        pipeline_version=PIPELINE_VERSION,
        vl_rec_model_name=VL_MODEL,
        layout_detection_model_name=LAYOUT_MODEL,
        # flags theo notebook user-proven; prod Colab worker không có
        # (parity ceiling — dễ bỏ cờ nếu tự thêm/sửa).
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
    )
    print(f"[batch] nạp model xong sau {time.time()-t0:.0f}s", flush=True)

    by_path = {str(p): p for p in todo}
    remaining = list(todo)

    def save(p, data, t):
        (raw_dir / f"{p.stem}.json").write_text(
            json.dumps(data, ensure_ascii=False, default=to_jsonable), encoding="utf-8"
        )
        err = raw_dir / f"{p.stem}.error.txt"
        if err.exists():
            err.unlink()
        print(f"[batch] {p.name}: xong ({t:.0f}s kể từ lúc bắt đầu)", flush=True)

    # Chế độ gộp: cả danh sách trang vào MỘT lần predict (use_queues mặc định
    # chạy song song: nạp trang -> layout -> VLM, GPU ít phải chờ).
    t1 = time.time()
    try:
        for res in pipeline.predict([str(p) for p in todo]):
            data = res.json
            inner = data.get("res", data) if isinstance(data, dict) else {}
            p = by_path.get(inner.get("input_path")) or remaining[0]  # kết quả theo thứ tự
            save(p, data, time.time() - t1)
            remaining.remove(p)
    except Exception:
        print("[batch] lỗi ở chế độ gộp, chạy tiếp từng trang cho phần còn lại", flush=True)
        print(traceback.format_exc(), flush=True)

    # Dự phòng: từng trang, trang lỗi không làm dừng cả file.
    for p in list(remaining):
        t2 = time.time()
        try:
            res = list(pipeline.predict(str(p)))[0]
            save(p, res.json, time.time() - t2)
            remaining.remove(p)
        except Exception:
            (raw_dir / f"{p.stem}.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            print(f"[batch] {p.name}: LỖI (xem {p.stem}.error.txt)", flush=True)
    return 0


# venv py3.12 (kaggle default py3.13 không có paddle wheel) — cheap
# constants, defined on import too (run_ocr re-exec target).
VENV_DIR = "/tmp/paddle-venv"
VENV_PY = os.path.join(VENV_DIR, "bin", "python")
PADDLE_PPU_INDEX = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"
# wheelhouse dataset jhandf/img2text-wheelbuild-env (75 cp312 manylinux
# wheels): install the venv with --no-index --find-links → ~1GB network
# saved per run. Deps list = wheelbuild build set.
WHEELHOUSE_DEPS = [
    "pillow", "numpy", "opencv-python-headless", "rapidfuzz",
    "pymupdf", "paddlepaddle-gpu", "paddleocr",
]

def _find_wheelhouse() -> str | None:
    """Mounted wheel dataset → its wheels dir (…/img2text-wheelbuild-env/**/
    wheels or a flat …/wheels); None = not mounted → caller falls back to
    the network pip installs (spawn must not crash on a missing dataset)."""
    hits = [
        d
        for d in glob.glob("/kaggle/input/**/wheels", recursive=True)
        if os.path.isdir(d)
    ]
    for d in hits:  # prefer the wheelbuild dataset if other dirs mount too
        if "img2text-wheelbuild-env" in d:
            return d
    return hits[0] if hits else None

if __name__ == "__main__":
    # --ocr re-exec dispatch (OCR phase, venv) — BEFORE the heavy bootstrap
    if len(sys.argv) > 1 and sys.argv[1] == "--ocr":
        sys.exit(_ocr_phase(sys.argv[2:]))

    # ===================================================================
    # Parent phase bootstrap (Kaggle kernel Python; pip/apt errors
    # check=False — verify after, never let install noise kill the script).
    # Script execution ONLY: importing this module (unit tests) must not
    # pip/apt/venv nor pull heavy deps (cv2/numpy/PIL/rapidfuzz).
    # ===================================================================
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=False)
    # pip --user uv lands in ~/.local/bin — make sure the `uv` name resolves.
    _local_bin = os.path.expanduser("~/.local/bin")
    if _local_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _local_bin
    subprocess.run(["apt-get", "-qq", "update"], check=False)
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "-q",
            "pillow", "numpy", "opencv-python-headless", "rapidfuzz", "PyMuPDF",
        ],
        check=False,
    )

    # Idempotent: venv đã có → bỏ qua cài (notebook pattern), chỉ verify import.
    if not os.path.exists(VENV_PY):
        subprocess.run(["uv", "venv", VENV_DIR, "--python", "3.12"], check=False)
        wheels_dir = _find_wheelhouse()
        if wheels_dir:
            # wheelhouse no-index (dataset đã mount): cài từ wheels, không
            # network — verify import ở dưới vẫn bắt mọi lỗi install.
            print(f"[batch] wheelhouse: {wheels_dir}", flush=True)
            subprocess.run(
                ["uv", "pip", "install", "--python", VENV_PY,
                 "--no-index", "--find-links", wheels_dir,
                 *WHEELHOUSE_DEPS],
                check=False,
            )
        else:
            # fallback: wheel dataset chưa mount → pip network như cũ
            for cmd in (
                [
                    "uv", "pip", "install", "--python", VENV_PY,
                    "paddlepaddle-gpu==3.2.1", "--extra-index-url", PADDLE_PPU_INDEX,
                ],
                [
                    "uv", "pip", "install", "--python", VENV_PY,
                    "paddleocr[doc-parser]>=3.6.0", "safetensors",
                    "tokenizers==0.22.2", "huggingface-hub>=0.25.0,<1.0",
                ],
            ):
                subprocess.run(cmd, check=False)

    if not os.path.exists(VENV_PY):
        # uv venv failed (no network/quota/python) — hint thay vì FileNotFoundError thô
        raise SystemExit(
            "venv py3.12/paddle không cài được — kiểm tra GPU/quota Kaggle + "
            "internet=true trong kernel Settings"
        )

    _paddle_check = subprocess.run(
        [VENV_PY, "-c", "import paddle, paddleocr; print(paddle.__version__, paddle.device.is_compiled_with_cuda())"],
        check=False,
        capture_output=True,
        text=True,
    )
    if _paddle_check.returncode != 0:
        raise SystemExit(
            "venv py3.12/paddle không cài được — kiểm tra GPU/quota Kaggle + "
            "internet=true trong kernel Settings"
        )
    print(f"venv paddle: {_paddle_check.stdout.strip()} (version, cuda_build)")

    import cv2  # noqa: E402
    import numpy as np  # noqa: E402
    from PIL import Image  # noqa: E402
    from rapidfuzz import fuzz  # noqa: E402

# ===========================================================================
# worker/verdict.py (flattened, FULL — precheck gates the OCR phase; resolve/
# similarity kept identical to the worker for spec §4 verdict parity).
# ===========================================================================

BLUR_LAPLACIAN_THRESHOLD = 100
MIN_WIDTH_PX = 1000

@dataclass
class PrecheckResult:
    blurry: bool
    too_small: bool


def precheck(img: np.ndarray) -> PrecheckResult:
    """Image quality precheck (Laplacian variance, width gate)."""
    if img is None or img.size == 0:
        raise ValueError("empty image array")
    if img.ndim == 2:
        gray = img
    elif img.ndim == 3 and img.shape[2] == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError(f"unsupported image shape: {img.shape}")
    # ponytail: glyph-height check (<20px estimated) is upgrade path, not implemented.
    blurry = float(cv2.Laplacian(gray, cv2.CV_64F).var()) < BLUR_LAPLACIAN_THRESHOLD
    too_small = img.shape[1] < MIN_WIDTH_PX
    return PrecheckResult(blurry=blurry, too_small=too_small)


@dataclass
class SourceResult:
    text: str
    confidence: float | None


@dataclass
class Region:
    id: str
    bbox: tuple[int, int, int, int] | None
    sources: dict[str, SourceResult]
    is_image: bool = False


_OCR_CONF_THRESHOLD = 0.7
_SIM_THRESHOLD = 0.85

_DIGIT_MAP = str.maketrans({"0": "o", "1": "l", "5": "s"})


def normalize_text(text: str) -> str:
    """lowercase, strip punctuation, collapse whitespace, map 0→o 1→l 5→s."""
    t = re.sub(r"[^\w\s]", "", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t.translate(_DIGIT_MAP)


def similarity(a: str, b: str) -> float:
    """0–1 fuzzy similarity on normalized text; empty-vs-empty is 0.0."""
    if not a and not b:
        return 0.0
    return fuzz.ratio(normalize_text(a), normalize_text(b)) / 100.0


def resolve(region: Region, page_flag: str) -> str:
    """Pinned resolution order: image > page_flag > empty vlm > dual branch > ok."""
    if region.is_image:
        return "image_unextractable"
    if page_flag == "unreadable":
        return "unreadable"
    if page_flag == "low_confidence":
        return "low_confidence"
    vlm = region.sources.get("vlm")
    if vlm is None or not vlm.text.strip():
        return "unreadable"
    ocr = region.sources.get("ocr")
    if ocr is not None:
        conf = ocr.confidence if ocr.confidence is not None else 0.0
        sim = similarity(vlm.text, ocr.text)
        if conf < _OCR_CONF_THRESHOLD:
            return "vlm_lowconf"
        return "ok" if sim >= _SIM_THRESHOLD else "ocr_preferred"
    return "ok"


# ===========================================================================
# worker/pipeline.py — batch pieces only. Server-loop pieces (run_job,
# _apply_preprocess, RunnerAuthError) dropped: no backend in batch mode.
# build_page/build_result adapter dropped by the amendment: the py3.12
# paddleocr[doc-parser] raw shape is parsing_res_list (cell 14 normalize),
# not the old {layout, markdown} shape those helpers consumed.
# ===========================================================================


def default_pdftoppm(pdf_bytes: bytes, file_type: str) -> list:
    """PyMuPDF rasterize → [(png_bytes, width, height), ...]."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        data = pix.tobytes("png")
        out.append((data, pix.width, pix.height))
    return out


# ===========================================================================
# Preprocess (VLM_OCR_pipeline(2).ipynb cell 9 verbatim) — nhẹ, giữ màu,
# không nhị phân hóa: deskew góc nhỏ, khử bóng theo kênh, giới hạn kích thước.
# ===========================================================================

DPI = 200
MAX_SIDE = 2500
DO_DESKEW = True
DO_SHADOW_REMOVE = True


def estimate_skew(gray, max_angle=5.0, step=0.25):
    h, w = gray.shape
    scale = 800 / max(h, w)
    small = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))),
                       interpolation=cv2.INTER_AREA)
    bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    best_angle, best_score = 0.0, -1.0
    sh, sw = bw.shape
    for a in np.arange(-max_angle, max_angle + step, step):
        M = cv2.getRotationMatrix2D((sw / 2, sh / 2), a, 1.0)
        rot = cv2.warpAffine(bw, M, (sw, sh), flags=cv2.INTER_NEAREST)
        score = np.var(rot.sum(axis=1).astype(np.float64))
        if score > best_score:
            best_score, best_angle = score, a
    return float(best_angle)


def rotate_keep_size(img, angle):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def remove_shadow(bgr):
    chans = []
    for c in cv2.split(bgr):
        dil = cv2.dilate(c, np.ones((7, 7), np.uint8))
        bg = cv2.medianBlur(dil, 21)
        diff = 255 - cv2.absdiff(c, bg)
        chans.append(cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX))
    return cv2.merge(chans)


def preprocess(path, out_path):
    img = cv2.imread(str(path))
    info = {"skew_deg": 0.0, "shadow_removed": False, "resized": False}
    if DO_DESKEW:
        angle = estimate_skew(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if abs(angle) >= 0.3:
            img = rotate_keep_size(img, angle)
            info["skew_deg"] = angle
    if DO_SHADOW_REMOVE:
        img = remove_shadow(img)
        info["shadow_removed"] = True
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        info["resized"] = True
    cv2.imwrite(str(out_path), img)
    info["width"], info["height"] = int(img.shape[1]), int(img.shape[0])
    return info


# ===========================================================================
# Parent-phase flow: locate → rasterize → precheck gate → preprocess →
# OCR (venv subprocess) → normalize (cell 14 shape) → write outputs.
# ===========================================================================

INPUT_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
WORK_DIR = "/tmp/img2text-batch"
# kernel_type "script" captures output from /kaggle/working (NOT
# /kaggle/outputs — that dir is only captured for notebook kernels).
# /kaggle/outputs kept as a harmless notebook-compat copy when creatable.
OUT_DIRS = ["/kaggle/working", "/kaggle/outputs"]


def _write_outputs(job_id: int, json_str: str, md_str: str) -> None:
    """Write {job_id}_result.{json,md} to every existing/creatable capture
    dir (per-job names — N jobs in one run must not overwrite each other)."""
    written = []
    for d in OUT_DIRS:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as exc:
            print(f"bỏ qua output dir {d}: {exc}")
            continue
        with open(os.path.join(d, f"{job_id}_result.json"), "w", encoding="utf-8") as f:
            f.write(json_str)
        with open(os.path.join(d, f"{job_id}_result.md"), "w", encoding="utf-8") as f:
            f.write(md_str)
        written.append(d)
    if not written:
        raise SystemExit("không ghi được output vào /kaggle/working hay /kaggle/outputs")
    for d in written:
        print(
            f"files ({d}): "
            f"{sorted(f for f in os.listdir(d) if f.startswith(f'{job_id}_result.'))}"
        )


def find_inputs(root: str = "/kaggle/input") -> list[tuple[int, str]]:
    """All staged inputs under root/** → (job_id, path), sorted by job_id.

    Server stages {job_id}__{orig} (spec 2026-10-09) — the numeric prefix is
    the unambiguous reverse mapping. New Kaggle mounts datasets under
    /kaggle/input/<owner>/<slug>/ → recursive glob. Skipped: dirs, unknown
    extensions (dataset-metadata.json), files without the {id}__ prefix or
    with a non-numeric prefix (dataset contents are never staged that way —
    must not be mistaken for a job); non-prefixed skips are logged.
    """
    found: list[tuple[int, str]] = []
    for p in sorted(glob.glob(os.path.join(root, "**", "*"), recursive=True)):
        if not os.path.isfile(p):
            continue
        name = os.path.basename(p)
        if os.path.splitext(name)[1].lower() not in INPUT_EXTS:
            continue
        head, sep, _ = name.partition("__")
        if not sep or not head.isdigit():
            print(f"[batch] bỏ qua input không có prefix job_id: {name}", flush=True)
            continue
        found.append((int(head), p))
    found.sort()
    return found


def rasterize_to_pages(input_path: str, raw_dir: str) -> list[str]:
    """Input → page_0001.png.. (raw_dir); returns sorted page paths."""
    os.makedirs(raw_dir, exist_ok=True)
    with open(input_path, "rb") as f:
        data = f.read()
    if input_path.lower().endswith(".pdf"):
        raster = default_pdftoppm(data, "pdf")
    else:
        im = Image.open(io.BytesIO(data))
        raster = [(data, im.size[0], im.size[1])]
    out = []
    for i, (png, _w, _h) in enumerate(raster, 1):
        p = os.path.join(raw_dir, f"page_{i:04d}.png")
        if input_path.lower().endswith(".pdf"):
            with open(p, "wb") as f:
                f.write(png)
        else:  # jpg/webp input → PNG (OCR phase globs page_*.png)
            Image.open(io.BytesIO(png)).save(p, "PNG")
        out.append(p)
    return out


def run_ocr(img_dir: str, raw_dir: str) -> None:
    """Re-exec THIS file under the py3.12 venv; pump [batch] lines (cell 12)."""
    os.makedirs(raw_dir, exist_ok=True)
    cmd = [VENV_PY, os.path.abspath(__file__), "--ocr", img_dir, raw_dir, "0"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    tail = []
    for line in proc.stdout:
        if "use GQA" in line:
            continue
        tail.append(line)
        tail = tail[-60:]
        if line.startswith("[batch]"):
            print(line, end="")
    proc.wait()
    if proc.returncode != 0:
        print("".join(tail))
        raise SystemExit(f"OCR phase exited {proc.returncode} — xem log ở trên")


def extract_blocks(raw: dict, page_no: int) -> list[dict]:
    """parsing_res_list → blocks (cell 14 verbatim shape)."""
    data = raw.get("res", raw) if isinstance(raw, dict) else {}
    items = data.get("parsing_res_list") or []
    blocks = []
    for i, it in enumerate(items):
        bbox = it.get("block_bbox")
        text = it.get("block_content") or ""
        blocks.append({
            "id": f"p{page_no}_b{i}",
            "order": i,
            "type": it.get("block_label") or "unknown",
            "bbox": [int(round(v)) for v in bbox] if bbox else None,
            "text": text,
            "empty": not text.strip(),
        })
    return blocks


def normalize(raw_paths: list[str], pre_info: dict,
              raw_dir: str, pre_dir: str) -> tuple[list[dict], list[str]]:
    """Cell-14 normalize → (pages_out, problems). Gated pages (no pre file)
    stay present: image = raw path, blocks [] + problems entry."""
    pages_out, problems = [], []
    for p in raw_paths:
        name = os.path.basename(p)
        page_no = int(name.split("_")[1].split(".")[0])
        pre_p = os.path.join(pre_dir, name)
        rj = os.path.join(raw_dir, f"page_{page_no:04d}.json")
        info = pre_info.get(name, {})
        if info.get("gated"):
            problems.append(f"{name}: precheck unreadable — không OCR")
        if not os.path.exists(rj):
            if not info.get("gated"):
                problems.append(f"{name}: chưa có kết quả OCR")
            pages_out.append({
                "page": page_no,
                "image": p if info.get("gated") else pre_p,
                "width": info.get("width"), "height": info.get("height"),
                "preprocess": {k: info[k] for k in
                               ("skew_deg", "shadow_removed", "resized") if k in info},
                "blocks": [],
            })
            continue
        with open(rj, encoding="utf-8") as f:
            raw = json.load(f)
        data = raw.get("res", raw)
        # bbox chỉ đúng nếu ảnh OCR đã đọc cùng kích thước với ảnh đang lưu
        if (data.get("width") and info.get("width")
                and (data["width"], data["height"]) != (info["width"], info["height"])):
            problems.append(
                f"{name}: kích thước OCR {data['width']}x{data['height']} khác "
                f"ảnh {info['width']}x{info['height']} (chạy lại với force OCR)"
            )
        pages_out.append({
            "page": page_no,
            "image": pre_p,
            "width": info.get("width"), "height": info.get("height"),
            "preprocess": {k: info[k] for k in
                           ("skew_deg", "shadow_removed", "resized") if k in info},
            "blocks": extract_blocks(raw, page_no),
        })
    return pages_out, problems


def process_job(job_id: int, input_path: str) -> None:
    """ONE staged input → pages → precheck gate → OCR → {job_id}_result.{json,md}.

    Per-job work dirs: page files are keyed page_0001.png — jobs sharing a
    dir would clobber each other (and the resumable OCR cache would serve
    the wrong pages)."""
    print(f"job {job_id}: {input_path}")
    job_dir = os.path.join(WORK_DIR, f"job_{job_id}")
    raw_dir = os.path.join(job_dir, "pages_raw")
    pre_dir = os.path.join(job_dir, "pages_pre")
    ocr_raw_dir = os.path.join(job_dir, "ocr_raw")
    os.makedirs(pre_dir, exist_ok=True)

    raw_paths = rasterize_to_pages(input_path, raw_dir)
    print(f"job {job_id}: rendered {len(raw_paths)} trang")

    # precheck gate (raw bytes — deskew/khử bóng không đổi độ mờ/kích thước
    # meaningfully): BOTH fail → bỏ qua OCR, trang vẫn có trong output.
    pre_info: dict[str, dict] = {}
    ready: list[str] = []
    for p in raw_paths:
        name = os.path.basename(p)
        arr = np.array(Image.open(p))
        pc = precheck(arr)
        if pc.blurry and pc.too_small:
            h, w = arr.shape[:2]
            pre_info[name] = {"width": w, "height": h, "gated": True}
            print(f"{name}: precheck unreadable (blurry+small) — bỏ qua OCR")
            continue
        pre_info[name] = preprocess(p, os.path.join(pre_dir, name))
        ready.append(os.path.join(pre_dir, name))

    if ready:
        run_ocr(pre_dir, ocr_raw_dir)

    pages_out, problems = normalize(raw_paths, pre_info,
                                    ocr_raw_dir, pre_dir)
    document = {"source_pdf": input_path, "dpi": DPI, "pages": pages_out,
                "problems": problems}  # → server batch adapter maps to result warnings
    md_pages = []
    for pg in pages_out:
        texts = [b["text"] for b in pg["blocks"] if not b["empty"]]
        md_pages.append("\n".join(texts))
    _write_outputs(
        job_id,
        json.dumps(document, ensure_ascii=False, indent=2),
        "\n\n---\n\n".join(md_pages),
    )
    for m in problems:
        print("LƯU Ý:", m)
    print(f"job {job_id}: pages: {len(pages_out)}")

def run_batch(inputs: list[tuple[int, str]]) -> int:
    """Run EVERY staged input — one job's failure must NOT stop the batch
    (log + continue; SystemExit from run_ocr/_write_outputs included).
    Returns 0 when ≥1 output written, else 1 (server: run failed → all jobs
    in the run fail at step extracting)."""
    written = 0
    for job_id, path in inputs:
        try:
            process_job(job_id, path)
            written += 1
        except (Exception, SystemExit) as exc:
            print(f"[batch] job {job_id} LỖI: {exc} — bỏ qua, chạy tiếp", flush=True)
    if not written:
        print("[batch] không ghi được output nào — exit 1", flush=True)
        return 1
    print(f"[batch] {written}/{len(inputs)} job ghi output", flush=True)
    return 0

def main() -> int:
    inputs = find_inputs()
    if not inputs:
        raise SystemExit(
            "no staged input ({job_id}__file, jpg/jpeg/png/webp/pdf) under "
            "/kaggle/input/** — spawn a batch run first"
        )
    print(f"inputs: {len(inputs)} job")
    return run_batch(inputs)


if __name__ == "__main__":
    sys.exit(main())
