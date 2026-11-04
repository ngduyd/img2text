"""Bench PHÂN RÃ 6 phút/trang — đo từng stage của đúng luồng production trên Kaggle T4.

Câu hỏi: 6 phút/trang ở production nằm ở đâu, khi bench cho thấy VLM native chỉ ~50 s/ảnh?
Đo theo đúng thứ tự kernel sản xuất (`img2text_batch.py` / `img2text_session.py`):

  1. bootstrap  — pip uv + uv venv + uv pip install (deps list verbatim)   ← nghi phạm chính
  2. import     — `import paddleocr` trong venv (Paddle + torch-free)
  3. load model — PaddleOCRVL(**prod flags)
  4. rasterize  — fitz 200dpi cho PDF 3 trang (ảnh demo ×3)
  5. precheck   — Laplacian variance + width gate (raw)
  6. preprocess — cv2: estimate_skew + rotate + remove_shadow + resize  ← nghi phạm 2
  7. predict    — predict từng trang (per-page, như production)
  8. crops      — fitz pixmap clip (rembg=None) và rembg u2net (nếu có image block)

Các hàm sinh thái copy verbatim từ `deploy/kaggle/kernel/img2text_batch.py` (không import được
vì kernel Kaggle script không kéo file phụ); hằng số giữ nguyên: DPI=200, MAX_SIDE=2500,
MAX_PAGE_SIDE=3000, DO_DESKEW/DO_SHADOW_REMOVE=True, BLUR_LAPLACIAN_THRESHOLD=100, MIN_WIDTH_PX=1000.
"""

import json
import os
import subprocess
import sys
import urllib.request

IMAGE_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/"
    "paddleocr_vl_demo.png"
)
PNG = "/tmp/stage_page.png"
PDF = "/tmp/stage_3p.pdf"
PADDLE_VENV = "/tmp/paddle-venv"
CLIENT = "/tmp/stage_client.py"
OUT = "/kaggle/working/bench_stages_result.json"
PAGES = int(os.environ.get("STAGE_PAGES") or 3)

CLIENT_SRC = r'''
import json, os, sys, time

def mark(name, t0, extra=None):
    dt = round(time.perf_counter() - t0, 2)
    print(f"[stage] {name}: {dt}s" + (f" {extra}" if extra else ""), flush=True)
    return dt

R = {}
PDF = sys.argv[1]
OUT = sys.argv[2]

t = time.perf_counter()
import numpy as np
import cv2
import fitz
R["import_base_s"] = mark("import numpy/cv2/fitz", t)

t = time.perf_counter()
from paddleocr import PaddleOCRVL
R["import_paddle_s"] = mark("import paddleocr", t)

# ---- verbatim constants/functions từ img2text_batch.py ----
DPI, MAX_SIDE, MAX_PAGE_SIDE = 200, 2500, 3000
DO_DESKEW = DO_SHADOW_REMOVE = True
BLUR_LAPLACIAN_THRESHOLD, MIN_WIDTH_PX = 100, 1000

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
    info = {"skew_deg": 0.0}
    if DO_DESKEW:
        angle = estimate_skew(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if abs(angle) >= 0.3:
            img = rotate_keep_size(img, angle)
            info["skew_deg"] = angle
    if DO_SHADOW_REMOVE:
        img = remove_shadow(img)
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        info["resized"] = True
    cv2.imwrite(str(out_path), img)
    return info

def precheck(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return (float(cv2.Laplacian(gray, cv2.CV_64F).var()) < BLUR_LAPLACIAN_THRESHOLD,
            img.shape[1] < MIN_WIDTH_PX)

# ---- 1. rasterize PDF ----
t = time.perf_counter()
doc = fitz.open(PDF)
pages = []
for page in doc:
    pix = page.get_pixmap(dpi=DPI)
    pages.append((pix.width, pix.height, pix.tobytes("png")))
R["rasterize_s"] = mark("rasterize fitz", t, f"{len(pages)} trang {pages[0][:2]}")
os.makedirs("/tmp/stage_pre", exist_ok=True)
raw = []
for i, (_w, _h, data) in enumerate(pages, 1):
    p = f"/tmp/stage_raw_{i}.png"
    open(p, "wb").write(data)
    raw.append(p)

# ---- 2. precheck ----
t = time.perf_counter()
flags = []
for p in raw:
    flags.append(precheck(np.array(cv2.imread(p))))
R["precheck_s"] = mark("precheck", t, f"{flags}")

# ---- 3. preprocess ----
t = time.perf_counter()
for p in raw:
    preprocess(p, "/tmp/stage_pre/" + os.path.basename(p))
R["preprocess_s"] = mark("preprocess cv2", t)

# ---- 4. load model ----
t = time.perf_counter()
pipeline = PaddleOCRVL(
    pipeline_version="v1.5",
    vl_rec_model_name="PaddleOCR-VL-1.5-0.9B",
    layout_detection_model_name="PP-DocLayoutV3",
    use_doc_orientation_classify=True,
    use_doc_unwarping=True,
)
R["load_model_s"] = mark("load PaddleOCRVL", t)

# ---- 5. predict từng trang ----
per = []
for i, p in enumerate(sorted(os.listdir("/tmp/stage_pre")), 1):
    t = time.perf_counter()
    res = list(pipeline.predict("/tmp/stage_pre/" + p))[0]
    data = res.json.get("res", res.json)
    per.append({"page": i, "s": mark(f"predict page {i}", t),
                "regions": len(data.get("parsing_res_list") or []),
                "image_blocks": sum(
                    1 for b in (data.get("parsing_res_list") or [])
                    if (b.get("block_label") or "") in ("image", "figure"))})
R["predict_pages"] = per
R["predict_total_s"] = round(sum(x["s"] for x in per), 2)

# ---- 6. crops: fitz clip (không rembg) rồi rembg ----
img_blocks = [b for b in (res.json.get("res", res.json).get("parsing_res_list") or [])
              if (b.get("block_label") or "") in ("image", "figure")]
R["crop_blocks_last_page"] = len(img_blocks)
if img_blocks:
    page = doc[-1]
    t = time.perf_counter()
    clips = [page.get_pixmap(clip=fitz.Rect(*img_blocks[0]["block_bbox"])).tobytes("png")]
    R["crop_fitz_s"] = mark("crop fitz 1 block", t, f"{len(clips[0])}B")
    t = time.perf_counter()
    try:
        from rembg import remove, new_session
        sess = new_session()
        R["rembg_session_s"] = mark("rembg new_session", t)
        t = time.perf_counter()
        remove(clips[0], session=sess)
        R["rembg_remove_s"] = mark("rembg remove 1 crop", t)
    except Exception as exc:
        R["rembg_error"] = f"{type(exc).__name__}: {exc}"
        print("[stage] rembg lỗi:", R["rembg_error"], flush=True)

json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=2)
print("[stage] RESULT", json.dumps(R, ensure_ascii=False), flush=True)
'''


def log(msg: str) -> None:
    print(f"[stage] {msg}", flush=True)


def run(cmd, **kw) -> int:
    log("$ " + " ".join(map(str, cmd)))
    return subprocess.run(cmd, check=False, **kw).returncode


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    result: dict = {"pages": PAGES, "gpu": subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True, check=False).stdout.strip()}
    log(f"GPU: {result['gpu']}")

    # PDF 3 trang từ ảnh demo (không có text layer — đúng kiểu ảnh chụp đề thi)
    import time
    t = time.perf_counter()
    urllib.request.urlretrieve(IMAGE_URL, PNG)
    run([sys.executable, "-m", "pip", "install", "-q", "pymupdf"])  # parent-side
    import fitz  # noqa: PLC0415
    doc = fitz.open()
    rect = fitz.open(PNG)[0].rect
    for _ in range(PAGES):
        page = doc.new_page(width=rect.width, height=rect.height)
        page.insert_image(page.rect, filename=PNG)
    doc.save(PDF)
    result["make_pdf_s"] = round(time.perf_counter() - t, 2)
    log(f"PDF {PAGES} trang: {os.path.getsize(PDF)}B")

    # 1. bootstrap — số quan trọng nhất: mỗi session Kaggle phải làm lại
    t = time.perf_counter()
    run([sys.executable, "-m", "pip", "install", "-q", "uv"])
    result["pip_uv_s"] = round(time.perf_counter() - t, 2)
    py = os.path.join(PADDLE_VENV, "bin", "python")

    t = time.perf_counter()
    run(["uv", "venv", PADDLE_VENV, "--python", "3.12"])
    result["venv_create_s"] = round(time.perf_counter() - t, 2)

    t = time.perf_counter()
    run(["uv", "pip", "install", "-p", py, "paddlepaddle-gpu==3.2.1",
         "--extra-index-url",
         "https://www.paddlepaddle.org.cn/packages/stable/cu126/"])
    result["pip_paddle_s"] = round(time.perf_counter() - t, 2)

    t = time.perf_counter()
    run(["uv", "pip", "install", "-p", py,
         "paddleocr[doc-parser]>=3.6.0", "safetensors", "rembg[cpu]", "pymupdf",
         "opencv-python-headless", "numpy", "rapidfuzz", "pillow"])
    result["pip_rest_s"] = round(time.perf_counter() - t, 2)
    result["bootstrap_total_s"] = round(
        result["pip_uv_s"] + result["venv_create_s"] + result["pip_paddle_s"]
        + result["pip_rest_s"], 2)
    log(f"bootstrap tổng: {result['bootstrap_total_s']}s")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 2..6 đo trong venv (paddle stack) — 1 process, có timer từng stage
    open(CLIENT, "w", encoding="utf-8").write(CLIENT_SRC)
    t = time.perf_counter()
    run([py, CLIENT, PDF, "/tmp/stages.json"])
    result["client_wall_s"] = round(time.perf_counter() - t, 2)
    try:
        result.update(json.load(open("/tmp/stages.json")))
    except Exception as exc:
        result["client_error"] = f"{type(exc).__name__}: {exc}"

    log(json.dumps(result, ensure_ascii=False))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
