"""Standalone Kaggle batch kernel (Plan K4) — ONE self-contained file.

kernel_type "script": pushed by deploy/kaggle/run_one.py — no worker-files
dataset, no sys.path mounts, no backend/secrets. Contains worker/verdict.py
(flattened, full) + the batch pieces of worker/pipeline.py + the proven flow
from VLM_OCR_pipeline(2).ipynb (cells 5/12/14).

Two phases, ONE file:
- parent phase (kernel Python, light deps): locate inputs — manifest.json
  mode (spec 2026-10-10: download each input_url + verify sha256) or mount
  fallback ({job_id}__ prefix glob) → rasterize (pdftoppm) → preprocess → precheck gate →
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
- OCR phase primary = predict TỪNG trang (1 pipeline, model load 1 lần) +
  SIGALRM watchdog (BATCH_PAGE_TIMEOUT || 600s/trang); batch generator mode
  chỉ còn sau BATCH_PREDICT=1. SIGALRM không interrupt được native/CUDA hang
  (upgrade path: subprocess watchdog từng trang, đổi lấy model reload).
- result.json = notebook document shape (pages[]/blocks[]), NOT prod spec §4;
  page `image` paths point at the kernel tmp dir (not pulled back);
- result.md = plain join block-text mỗi trang — batch-grade, khác worker prod
  (bỏ image-block, không Cảnh-báo marker/page_flag). sync production sau.
"""
from __future__ import annotations
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass

# ===========================================================================
# OCR phase — re-exec'd under /tmp/paddle-venv/bin/python (argv: --ocr img raw).
# Runs BEFORE any bootstrap/heavy import: the venv has paddleocr only.
# Mirrors VLM_OCR_pipeline(2).ipynb cell 12 (load model once, resumable).
# ===========================================================================

PIPELINE_VERSION = "v1.5"
VL_MODEL = "PaddleOCR-VL-1.5-0.9B"
LAYOUT_MODEL = "PP-DocLayoutV3"
# Parity với server app.core.schemas.IMAGE_MARKER (kernel standalone không
# import server được — hằng copy, test pin parity); exports._materialize_crops
# rewrite marker này thành ảnh crop khi render/export.
IMAGE_MARKER = "**[Hình ảnh chưa trích xuất: vùng {region_id}]**"


class PagePredictTimeout(RuntimeError):
    """SIGALRM watchdog: predict 1 trang quá BATCH_PAGE_TIMEOUT."""

def _alarm_handler(signum, frame):  # noqa: ARG001
    raise PagePredictTimeout()

def _page_timeout() -> float:
    """BATCH_PAGE_TIMEOUT (giây/trang, mặc định 600) — env rỗng/sai giá trị
    → mặc định (typo env không được kill cả OCR phase)."""
    v = os.environ.get("BATCH_PAGE_TIMEOUT") or ""
    try:
        return float(v) if v else 600.0
    except ValueError:
        return 600.0

def _log_gpu(tag: str) -> None:
    """Dòng [gpu] sau MỖI trang (alloc/reserved MB) — xác nhận GPU giữ cache
    giữa các trang hay reset/tràn. GPU_EMPTY_CACHE=1 → empty_cache() sau log
    (mặc định OFF: run đầu quan sát hành vi tự nhiên). Thiếu paddle/CPU env
    → in dòng lỗi, không kill OCR phase."""
    try:
        import paddle
        alloc = paddle.device.cuda.memory_allocated() / (1024 * 1024)
        reserved_fn = getattr(paddle.device.cuda, "memory_reserved", None)
        if reserved_fn is None:  # bản paddle thiếu reserved → peak counter
            reserved_fn = paddle.device.cuda.max_memory_allocated
        reserved = reserved_fn() / (1024 * 1024)
    except Exception as exc:
        print(f"[gpu] {tag}: không đọc được ({exc})", flush=True)
        return
    print(f"[gpu] {tag}: alloc={alloc:.0f}MB reserved={reserved:.0f}MB", flush=True)
    if (os.environ.get("GPU_EMPTY_CACHE") or "") == "1":
        paddle.device.cuda.empty_cache()

def _predict_pages_one_by_one(pipeline, pages, save, raw_dir,
                              timeout: float | None = None) -> None:
    """PRIMARY (lane H OCR perf): predict TỪNG trang, GIỮ 1 pipeline instance
    (model load 1 lần) — batch generator mode (treo im lặng ~1h với ảnh
    pathological) chỉ còn sau BATCH_PREDICT=1. Mỗi trang bọc SIGALRM
    (setitimer): quá timeout → PagePredictTimeout → error.txt (như nhánh
    exception), sang trang sau. GPU log sau MỖI trang.

    ceiling (ponytail): SIGALRM chỉ raise khi bytecode Python chạy — predict
    kẹt trong native/CUDA call không nhường GIL/bytecode → vẫn treo; upgrade
    path = subprocess watchdog từng trang (đổi lấy model reload ~26s/trang).
    Sau timeout GIỮ instance — trang sau cũng fail → error.txt, chạy tiếp."""
    import signal
    import traceback

    timeout = _page_timeout() if timeout is None else timeout
    for p in pages:
        t2 = time.time()
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            res = list(pipeline.predict(str(p)))[0]
            save(p, res.json, time.time() - t2)
        except PagePredictTimeout:
            (raw_dir / f"{p.stem}.error.txt").write_text(
                f"predict quá {timeout:g}s (BATCH_PAGE_TIMEOUT) — bỏ qua trang",
                encoding="utf-8")
            print(f"[batch] {p.name}: TIMEOUT {timeout:g}s (xem {p.stem}.error.txt)",
                  flush=True)
        except Exception:
            (raw_dir / f"{p.stem}.error.txt").write_text(
                traceback.format_exc(), encoding="utf-8")
            print(f"[batch] {p.name}: LỖI (xem {p.stem}.error.txt)", flush=True)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)  # hủy watchdog khi ra khỏi trang
        _log_gpu(p.stem)

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

    def save(p, data, t):
        (raw_dir / f"{p.stem}.json").write_text(
            json.dumps(data, ensure_ascii=False, default=to_jsonable), encoding="utf-8"
        )
        err = raw_dir / f"{p.stem}.error.txt"
        if err.exists():
            err.unlink()
        print(f"[batch] {p.name}: xong ({t:.0f}s kể từ lúc bắt đầu)", flush=True)

    if os.environ.get("BATCH_PREDICT") != "1":
        # PRIMARY (lane H): từng trang + SIGALRM watchdog + GPU log; batch
        # generator mode giữ nguyên bên dưới (chỉ chạy khi BATCH_PREDICT=1)
        _predict_pages_one_by_one(pipeline, todo, save, raw_dir)
        return 0

    by_path = {str(p): p for p in todo}
    remaining = list(todo)

    # Chế độ gộp (BATCH_PREDICT=1, default OFF — lane H: batch-mode treo im
    # lặng ~1h với ảnh pathological, không có per-page watchdog): cả danh sách
    # trang vào MỘT lần predict (use_queues mặc định chạy song song: nạp trang
    # -> layout -> VLM, GPU ít phải chờ).
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
    "pymupdf", "paddlepaddle-gpu==3.2.1", "paddleocr[doc-parser]>=3.6.0",
    "safetensors", "tokenizers==0.22.2", "huggingface-hub>=0.25.0,<1.0",
    "rembg[cpu]",  # WS-PIPE crop — thiếu → extract_crops ImportError
    "pillow-heif",  # review r1 P0-2 — server cho phép heic/heif; thiếu → Image.open chết
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
            "rembg[cpu]",  # WS-PIPE: crop remove-background (u2net, model cache U2NET_HOME)
            "pillow-heif",  # review r1 P0-2: rasterize ở PARENT phase — heic/heif decode
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
            # Repair: wheelhouse drift (thiếu paddle/doc-parser extras) →
            # cài full recipe proven từ network (paddle cu126 + doc-parser stack).
            if subprocess.run(
                [VENV_PY, "-c", "import paddle, paddleocr, rembg, pillow_heif"], capture_output=True
            ).returncode != 0:
                print("[batch] wheelhouse thiếu deps — repair full recipe từ network", flush=True)
                for cmd in (
                    ["uv", "pip", "install", "--python", VENV_PY,
                     "paddlepaddle-gpu==3.2.1", "--extra-index-url", PADDLE_PPU_INDEX],
                    ["uv", "pip", "install", "--python", VENV_PY,
                     "paddleocr[doc-parser]>=3.6.0", "safetensors", "pillow-heif",
                     "tokenizers==0.22.2", "huggingface-hub>=0.25.0,<1.0",
                     "rembg[cpu]"],
                ):
                    subprocess.run(cmd, check=False)
        else:
            # fallback: wheel dataset chưa mount → pip network như cũ
            for cmd in (
                [
                    "uv", "pip", "install", "--python", VENV_PY,
                    "paddlepaddle-gpu==3.2.1", "--extra-index-url", PADDLE_PPU_INDEX,
                ],
                [
                    "uv", "pip", "install", "--python", VENV_PY,
                    "paddleocr[doc-parser]>=3.6.0", "safetensors", "pillow-heif",
                    "tokenizers==0.22.2", "huggingface-hub>=0.25.0,<1.0",
                    "rembg[cpu]",
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
        [VENV_PY, "-c", "import paddle, paddleocr, rembg, pillow_heif; print(paddle.__version__, paddle.device.is_compiled_with_cuda())"],
        check=False,
        capture_output=True,
        text=True,
    )
    if _paddle_check.returncode != 0:
        # hiện stderr thật — cài đặt OK nhưng import fail là lỗi khác hẳn
        # (driver/CUDA/lib missing); message chung chung khiến log mù nguyên nhân.
        detail = (_paddle_check.stderr or "").strip()[-1500:] or _paddle_check.stdout.strip()[-1500:]
        raise SystemExit(
            "venv py3.12/paddle: import FAIL (đã cài xong) — stderr:\n" + detail
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
# RunnerAuthError) dropped: no backend in batch mode. _apply_preprocess giữ
# bản file-based (wave-2 #4 — page-select + rotate trước OCR, R55 tên trang).
# ===========================================================================
# build_page/build_result adapter dropped by the amendment: the py3.12
# paddleocr[doc-parser] raw shape is parsing_res_list (cell 14 normalize),
# not the old {layout, markdown} shape those helpers consumed.
# ===========================================================================


def default_pdftoppm(pdf_bytes: bytes, file_type: str) -> list:
    """PyMuPDF rasterize → [(png_bytes, width, height), ...]. Real page
    count > MAX_PDF_PAGES → raise BEFORE rasterizing (client page_count
    untrusted; a 500-page PDF must not burn the GPU quota)."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count > MAX_PDF_PAGES:
        raise RuntimeError(
            f"PDF {doc.page_count} trang — quá {MAX_PDF_PAGES}, bỏ qua"
        )
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
# lane H (OCR perf): rasterize downscale jpg/webp có max side > 3000 → 3000
# (LANCZOS, giữ tỉ lệ) TRƯỚC khi save page PNG — precheck/cv2.imread/PNG
# encode không đụng full-res. scale bbox→tọa độ gốc trong extract_crops
# tự lấy từ page.rect/w_px (đã BAO TRỘN hệ số rasterize + preprocess) —
# scales.json chỉ là ghi chú audit, KHÔNG được chia thêm vào bbox (double).
MAX_PAGE_SIDE = 3000
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
# R2 ceilings — mirror server MAX_UPLOAD_BYTES / MAX_PDF_PAGES: the
# manifest/client metadata is NOT trusted at batch time.
MAX_INPUT_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 100
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


def _write_crop_outputs(job_id: int, crops: dict[str, bytes]) -> None:
    """{job_id}_crop_{rid}.png → mọi output dir (cùng contract result.json:
    script kernel capture /kaggle/working; orchestrator ingest từ đó)."""
    for d in OUT_DIRS:
        if not os.path.isdir(d):
            continue
        for rid, png in crops.items():
            with open(os.path.join(d, f"{job_id}_crop_{rid}.png"), "wb") as f:
                f.write(png)
        print(f"crops ({d}): {sorted(crops)}", flush=True)

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


def fetch_input(url: str, dest: str, sha256: str | None = None,
                timeout: float = 120.0) -> None:
    """Manifest mode (spec 2026-10-10): download presigned url → dest,
    verify sha256 WHILE streaming; >MAX_INPUT_BYTES mid-stream → dest
    removed + RuntimeError (server content-length-range spirit, enforced
    client-side too). Mismatch → same (per-job partial-fail đã có)."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    req = urllib.request.Request(url, headers={"User-Agent": "img2text-batch"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_INPUT_BYTES:
                    raise RuntimeError(
                        f"input quá {MAX_INPUT_BYTES // (1024 * 1024)}MB — bỏ qua {dest}"
                    )
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        if os.path.exists(dest):
            os.remove(dest)
        raise
    if sha256 is not None and digest.hexdigest() != sha256:
        os.remove(dest)
        raise RuntimeError(f"sha256 không khớp — bỏ qua {dest}")

def load_manifest(root: str = "/kaggle/input") -> list[dict] | None:
    """manifest.json dưới mount (Kaggle nests /kaggle/input/<owner>/<slug>/);
    None = không có manifest → mount fallback (dev localstack)."""
    hits = sorted(glob.glob(os.path.join(root, "**", "manifest.json"), recursive=True))
    if not hits:
        return None
    with open(hits[0], encoding="utf-8") as f:
        data = json.load(f)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    # malformed manifest (non-dict root / jobs not list-of-dict) → None =
    # mount fallback; a corrupted manifest must not crash the batch.
    if not isinstance(jobs, list) or not all(isinstance(j, dict) for j in jobs):
        return None
    return jobs

def fetch_manifest_jobs(jobs: list[dict], dest_dir: str,
                        root: str = "/kaggle/input") -> list[tuple[int, str, dict | None]]:
    """manifest entries → (job_id, downloaded path, preprocess|None); download
    fail (URL hết hạn/network) → mount fallback ({job_id}__* đã mount, preprocess
    None) → still missing → bỏ qua job đó (batch chạy tiếp)."""
    os.makedirs(dest_dir, exist_ok=True)
    mounted = find_inputs(root)
    out: list[tuple[int, str, dict | None]] = []
    for entry in jobs:
        job_id = int(entry["job_id"])
        pp = entry.get("preprocess") or None
        dest = os.path.join(dest_dir, entry["filename"])
        try:
            fetch_input(entry["input_url"], dest, entry.get("sha256"))
            out.append((job_id, dest, pp))
            continue
        except Exception as exc:
            print(f"[batch] job {job_id} tải input lỗi: {exc} — thử mount fallback", flush=True)
        fallback = next((p for jid, p in mounted if jid == job_id), None)
        if fallback is None:
            print(f"[batch] job {job_id} không có input — bỏ qua", flush=True)
            continue
        out.append((job_id, fallback, None))  # mount fallback: không có manifest → không preprocess
    return out

def _register_heif_opener() -> None:
    """review r1 P0-2: server cho phép heic/heif nhưng Pillow native không
    decode HEIF — pillow-heif optional (wheelhouse + network recipe). Import
    lỗi → bỏ qua (env không có lib; AVIF Pillow native)."""
    try:
        import pillow_heif
    except ImportError:
        return
    pillow_heif.register_heif_opener()

def rasterize_to_pages(input_path: str, raw_dir: str) -> list[str]:
    """Input → page_0001.png.. (raw_dir); returns sorted page paths.

    EXIF-rotate trước OCR: ảnh JPEG orientation tag (phone camera) được
    exif_transpose → PNG đúng chiều thật (OCR đọc pixels, không đọc EXIF).
    Ảnh jpg/webp max side > MAX_PAGE_SIDE → downscale về 3000 + ghi tỉ lệ
    mới/cũ vào raw_dir/../scales.json ({page_stem: scale}); PDF giữ nguyên
    (pdftoppm 200dpi)."""
    from PIL import Image, ImageOps

    _register_heif_opener()
    os.makedirs(raw_dir, exist_ok=True)
    with open(input_path, "rb") as f:
        data = f.read()
    if input_path.lower().endswith(".pdf"):
        raster = default_pdftoppm(data, "pdf")
    else:
        with Image.open(io.BytesIO(data)) as im:
            raster = [(data, im.size[0], im.size[1])]
    out = []
    scales: dict[str, float] = {}
    for i, (png, _w, _h) in enumerate(raster, 1):
        p = os.path.join(raw_dir, f"page_{i:04d}.png")
        if input_path.lower().endswith(".pdf"):
            with open(p, "wb") as f:
                f.write(png)
        else:  # jpg/webp input → PNG (OCR phase globs page_*.png)
            with Image.open(io.BytesIO(png)) as im:
                im = ImageOps.exif_transpose(im)
                w, h = im.size
                if max(w, h) > MAX_PAGE_SIDE:  # lane H: downscale trước save
                    s = MAX_PAGE_SIDE / max(w, h)
                    im = im.resize((max(1, round(w * s)), max(1, round(h * s))),
                                   Image.LANCZOS)
                    scales[os.path.splitext(os.path.basename(p))[0]] = s
                im.save(p, "PNG")
        out.append(p)
    scales_p = os.path.join(
        os.path.dirname(os.path.abspath(raw_dir)), "scales.json")
    if scales:
        with open(scales_p, "w", encoding="utf-8") as f:
            json.dump(scales, f, ensure_ascii=False, indent=2)
    elif os.path.exists(scales_p):
        # dev/resume dir cũ có downscale, run này không → scales cũ sai lệch
        os.remove(scales_p)
    return out


def _apply_preprocess(page_paths: list[str], preprocess_spec: dict | None
                      ) -> list[str]:
    """Chọn trang + xoay CLOCKWISE trước OCR (wave-2 #4; worker loop
    _apply_preprocess pattern — bản file-based).

    pages: GIỮ file trang được chọn (1-based); tên file = số trang gốc
    (R55 — normalize derive page_no từ tên, không renumber); trang bị loại
    bị XÓA khỏi disk. rotate: {"<page>": 90|180|270} xoay tại chỗ (0/absent
    = bytes giữ nguyên). None/pages thiếu → giữ nguyên mọi trang."""
    from PIL import Image, ImageOps
    _register_heif_opener()
    if not preprocess_spec:
        return page_paths
    pages_sel = preprocess_spec.get("pages")
    rotate = preprocess_spec.get("rotate") or {}
    cw = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
    out: list[str] = []
    for p in page_paths:
        n = int(os.path.basename(p).split("_")[1].split(".")[0])
        if pages_sel is not None and n not in pages_sel:
            os.remove(p)
            continue
        v = int(rotate.get(str(n), 0) or 0)
        if v in cw:
            # review r1 P1-5: `with` đóng handle (Image.open fp leak khi loop nhiều trang)
            with Image.open(p) as im:
                # exif_transpose trước xoay: PNG page đã transpose ở
                # rasterize → no-op ở đây (defensive cho mount fallback)
                ImageOps.exif_transpose(im).transpose(cw[v]).save(p, "PNG")
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
        block = {
            "id": f"p{page_no}_b{i}",
            "order": i,
            "type": it.get("block_label") or "unknown",
            "bbox": [int(round(v)) for v in bbox] if bbox else None,
            "text": text,
            "empty": not text.strip(),
        }
        if "<table" in text.lower():
            # wave-3: parse MỘT LẦN ở kernel — html = nguồn sự thật,
            # cells = rows [{text,rowspan,colspan,header}], text = phẳng
            cells = _parse_table_html(text)
            if cells:
                block["html"], block["cells"] = text, cells
                block["text"] = _cells_to_flat(cells)
            else:
                print(f"[batch] table {block['id']} không parse được — giữ HTML gốc",
                      flush=True)
        blocks.append(block)
    return blocks

# ===========================================================================
# wave-3 (spec 2026-10-13): bảng cells → md GFM pipe + reading order 2 cột.
# ===========================================================================

def _safe_span(v) -> int:
    """rowspan/colspan attr → int ≥1; không parse được hoặc ≤0 → 1
    (P1: giá trị "foo"/"2.0" không được ValueError giết cả job)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 1
    return n if n >= 1 else 1

def _parse_table_regex(html: str) -> list[list[dict]]:
    """regex fallback của _parse_table_html (env không có bs4)."""
    rows: list[list[dict]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        row: list[dict] = []
        for m in re.finditer(
            r"<t([dh])([^>]*)>(.*?)</t\1>", tr, re.DOTALL | re.IGNORECASE
        ):
            spans = {
                k.lower(): _safe_span(v)
                for k, v in re.findall(
                    r'(rowspan|colspan)\s*=\s*["\']?(\d+)["\']?', m.group(2), re.I
                )
            }
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(3))).strip()
            row.append({
                "text": text,
                "rowspan": spans.get("rowspan", 1),
                "colspan": spans.get("colspan", 1),
                "header": m.group(1).lower() == "h",
            })
        if row:
            rows.append(row)
    return rows

def _parse_table_html(html: str) -> list[list[dict]]:
    """<table> HTML → rows [{text,rowspan,colspan,header}] — bs4 (kernel venv
    có paddlex deps) hoặc regex fallback (unit-test env không bs4)."""
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415 (lazy — import test cheap)
    except ImportError:
        return _parse_table_regex(html)
    soup = BeautifulSoup(html, "html.parser")
    rows: list[list[dict]] = []
    # ceiling (P2-3): find_all("tr") KHÔNG giới hạn table outermost — tr của
    # bảng nested bị flatten lẫn hàng ngoài. Upgrade khi corpus có nested:
    # find outermost table rồi scope find_all("tr") trong nó.
    for tr in soup.find_all("tr"):
        row: list[dict] = []
        for td in tr.find_all(["td", "th"], recursive=False):
            row.append({
                "text": td.get_text(" ", strip=True),
                "rowspan": _safe_span(td.get("rowspan")),
                "colspan": _safe_span(td.get("colspan")),
                "header": td.name == "th",
            })
        if row:
            rows.append(row)
    return rows

def _cell_texts(row: list[dict]) -> list[str]:
    """colspan → lặp text ô; rowspan → bỏ (GFM pipe không có span — docx giữ)."""
    out: list[str] = []
    for c in row:
        out.extend([str(c.get("text") or "")] * max(1, int(c.get("colspan") or 1)))
    return out

def _cells_to_flat(cells: list[list[dict]]) -> str:
    """cells → text phẳng (hàng join ' | ', dòng xuống hàng) — result.jsonb
    regions dùng cái này."""
    return "\n".join(" | ".join(_cell_texts(r)) for r in cells)

def _table_cells_to_md(cells: list[list[dict]]) -> str:
    """cells → GFM pipe table: hàng có th (hoặc hàng đầu) = header + separator."""
    if not cells:
        return ""
    h = next(
        (i for i, r in enumerate(cells) if any(c.get("header") for c in r)), 0
    )
    def fmt(row: list[dict]) -> str:
        cells_txt = [t.replace("|", "\\|") for t in _cell_texts(row)]
        return "| " + " | ".join(cells_txt) + " |"
    lines = [fmt(cells[h]), "| " + " | ".join(["---"] * len(_cell_texts(cells[h]))) + " |"]
    lines += [fmt(r) for i, r in enumerate(cells) if i != h]
    return "\n".join(lines)

def _band_tol(h1: float, h2: float) -> float:
    """Y-band tolerance (spec wave-3: max(10, height*0.3))."""
    return max(10.0, 0.3 * max(h1, h2))

def _linearize_reading_order(blocks: list[dict]) -> list[dict]:
    """Reading order: y-bands theo center y (tolerance _band_tol) → mỗi band
    sort x0 trái→phải → flatten (2 cột cùng hàng: trái trước)."""
    keyed = []
    for i, b in enumerate(blocks):
        bbox = b.get("bbox")
        if bbox:
            cy, h, x0 = (bbox[1] + bbox[3]) / 2, abs(bbox[3] - bbox[1]), bbox[0]
        else:  # không bbox — giữ cuối, theo thứ tự gốc
            cy, h, x0 = float("inf"), 0.0, float("inf")
        keyed.append((cy, h, x0, i, b))
    keyed.sort(key=lambda t: (t[0], t[3]))
    bands: list[list[tuple]] = []
    for t in keyed:
        if (bands and t[0] != float("inf")
                and t[0] - bands[-1][-1][0] <= _band_tol(t[1], bands[-1][-1][1])):
            bands[-1].append(t)
        else:
            bands.append([t])
    return [
        b
        for band in bands
        for _, _, _, _, b in sorted(band, key=lambda t: (t[2], t[3]))
    ]

def _page_md(blocks: list[dict]) -> str:
    """blocks → md 1 trang: reading order; image → IMAGE_MARKER (2 marker cùng
    hàng = 1 dòng cách space, marker lẻ = dòng riêng); table có cells → GFM
    pipe; còn lại text thường."""
    parts: list[str] = []
    last_marker: tuple | None = None  # (center_y, height) của marker vừa emit
    for b in _linearize_reading_order(blocks):
        is_image = b.get("type") == "image"
        if b.get("empty") and not is_image:
            continue
        pos = None
        if is_image:
            piece = IMAGE_MARKER.format(region_id=b.get("id"))
            bbox = b.get("bbox")
            if bbox:
                pos = ((bbox[1] + bbox[3]) / 2, abs(bbox[3] - bbox[1]))
        elif b.get("cells"):
            piece = _table_cells_to_md(b["cells"])
        else:
            piece = b.get("text") or ""
        if not piece or not piece.strip():
            continue
        if (parts and last_marker is not None and pos is not None
                and abs(pos[0] - last_marker[0]) <= _band_tol(pos[1], last_marker[1])):
            parts[-1] += " " + piece  # 2 marker cùng hàng → CÙNG dòng
        else:
            parts.append(piece)
        last_marker = pos
    return "\n\n".join(parts)


def _to_original_bbox(bbox, scale):
    """bbox px trên ảnh ĐÃ preprocess (OCR coord) → bbox trên trang/ảnh GỐC
    (fitz clip coord). scale = original_size / preprocessed_size — CHUNG cho
    PDF (page.rect pt) và image (page.rect px); preprocess resize giữ aspect
    (rotate_keep_size không đổi kích thước) nên 1 factor đủ."""
    x0, y0, x1, y1 = bbox
    return [x0 * scale, y0 * scale, x1 * scale, y1 * scale]

def extract_crops(input_path: str, pages_out: list, remove=None) -> dict[str, bytes]:
    """WS-PIPE: image blocks (type==\"image\", có bbox) → PyMuPDF
    page.get_pixmap(clip=bbox px→pt) → PNG → rembg.remove → {rid: png_bytes}.

    bbox trong result là px @DPI trên ảnh đã rasterize → đổi sang pt (72dpi)
    rồi scale ngược khi lấy pixmap (giữ ~DPI resolution). Input ảnh thường:
    fitz mở 1 trang với rect = px → scale = rect.width/width_px. remove=None →
    rembg lazy (kernel phase); test inject stub. Partial-fail: 1 crop lỗi →
    log + bỏ region đó, không kill job (run_batch đã catch ở mức job)."""
    import fitz
    if remove is None:
        # u2net.onnx cache trong wheelbuild dataset (task 1) → rembg không tải
        hits = glob.glob("/kaggle/input/**/u2net.onnx", recursive=True)
        if hits:
            os.environ.setdefault("U2NET_HOME", os.path.dirname(hits[0]))
        from rembg import remove as remove  # noqa: PLC0415 (lazy — import test cheap)
    doc = fitz.open(input_path)
    try:
        crops: dict[str, bytes] = {}
        for pg in pages_out:
            w_px = pg.get("width") or 0
            if not w_px or not (1 <= int(pg.get("page") or 0) <= doc.page_count):
                continue
            page = doc[int(pg["page"]) - 1]
            # bbox = px ảnh preprocess (OCR đọc bản đó) → trang gốc:
            # scale = original rect / preprocessed size (PDF pt, image px)
            scale = page.rect.width / w_px
            for b in pg.get("blocks") or []:
                if b.get("type") != "image" or not b.get("bbox"):
                    continue
                rid = str(b["id"])
                x0, y0, x1, y1 = _to_original_bbox(b["bbox"], scale)
                clip = fitz.Rect(x0, y0, x1, y1)
                try:
                    # 72dpi mặc định → crop mờ; Matrix(2,2) = 144dpi đủ sharp
                    pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2))
                    png = pix.tobytes("png")
                    crops[rid] = remove(png)
                except Exception as exc:  # partial-fail 1 crop
                    print(f"[batch] crop {rid} lỗi: {exc}", flush=True)
        return crops
    finally:
        doc.close()

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


def process_job(job_id: int, input_path: str,
                preprocess_spec: dict | None = None) -> None:
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

    raw_paths = _apply_preprocess(
        rasterize_to_pages(input_path, raw_dir), preprocess_spec
    )
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
    # WS-PIPE: image block → crop + rembg (partial-fail đã nuốt trong extract)
    try:
        crops = extract_crops(input_path, pages_out)
    except Exception as exc:  # rembg/fitz lỗi chung → job vẫn ra kết quả
        crops = {}
        print(f"job {job_id}: crop extract lỗi: {exc}", flush=True)
    if crops:
        _write_crop_outputs(job_id, crops)
    document = {"source_pdf": input_path, "dpi": DPI, "pages": pages_out,
                "problems": problems}  # → server batch adapter maps to result warnings
    md_pages = [_page_md(pg["blocks"]) for pg in pages_out]
    _write_outputs(
        job_id,
        json.dumps(document, ensure_ascii=False, indent=2),
        "\n\n---\n\n".join(md_pages),
    )
    for m in problems:
        print("LƯU Ý:", m)
    print(f"job {job_id}: pages: {len(pages_out)}")

def run_batch(inputs: list[tuple[int, str, dict | None]]) -> int:
    """Run EVERY staged input — one job's failure must NOT stop the batch
    (log + continue; SystemExit from run_ocr/_write_outputs included).
    Returns 0 when ≥1 output written, else 1 (server: run failed → all jobs
    in the run fail at step extracting)."""
    written = 0
    for job_id, path, preprocess in inputs:
        try:
            process_job(job_id, path, preprocess)
            written += 1
        except (Exception, SystemExit) as exc:
            print(f"[batch] job {job_id} LỖI: {exc} — bỏ qua, chạy tiếp", flush=True)
    if not written:
        print("[batch] không ghi được output nào — exit 1", flush=True)
        return 1
    print(f"[batch] {written}/{len(inputs)} job ghi output", flush=True)
    return 0

def main() -> int:
    manifest = load_manifest()
    if manifest:
        print(f"manifest: {len(manifest)} job (URL mode)", flush=True)
        inputs = fetch_manifest_jobs(manifest, os.path.join(WORK_DIR, "inputs"))
    else:
        inputs = [(jid, p, None) for jid, p in find_inputs()]  # mount fallback (dev)
    if not inputs:
        raise SystemExit(
            "no staged input ({job_id}__file, jpg/jpeg/png/webp/pdf) under "
            "/kaggle/input/** — spawn a batch run first"
        )
    print(f"inputs: {len(inputs)} job")
    return run_batch(inputs)


if __name__ == "__main__":
    sys.exit(main())
