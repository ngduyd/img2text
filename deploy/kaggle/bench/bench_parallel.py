"""Prototype SONG SONG HOÁ cold start (đo trên Kaggle T4).

Ý tưởng: phần "không cần paddle" (rasterize + preprocess + tải u2net + rembg cả trang = ~125 s đo được)
chạy CHỒNG với `uv pip install paddlepaddle-gpu` (177–1028 s). Sau đó mới import + load model + predict.

Đo để trả lời: cold start giảm được bao nhiêu so với chuỗi tuần tự hiện tại
(321 s = pip 177 + import 9 + load model 25 + u2net 110 theo số cũ).

Cũng kiểm `which uv` — nếu Kaggle image đã có uv thì bỏ được `pip install uv` (3,8–8,6 s).
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

IMAGE_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/"
    "paddleocr_vl_demo.png"
)
PNG = "/tmp/par_page.png"
PDF = "/tmp/par_1p.pdf"
PRE = "/tmp/par_pre.png"
VENV = "/tmp/paddle-venv"
VLLM_VENV = "/tmp/vllm-venv"  # chỉ để dành venv riêng; không dùng ở đây
OUT = "/kaggle/working/bench_parallel_result.json"
PADDLE_IDX = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"

CLIENT_SRC = r'''
import json, sys, time
PRE, OUT = sys.argv[1], sys.argv[2]
R = {}
def mark(name, t0):
    dt = round(time.perf_counter() - t0, 2)
    print(f"[par] {name}: {dt}s", flush=True)
    return dt

t = time.perf_counter()
import numpy as np, cv2
R["import_base_s"] = mark("import numpy/cv2", t)

t = time.perf_counter()
from paddleocr import PaddleOCRVL
R["import_paddle_s"] = mark("import paddleocr", t)

t = time.perf_counter()
pipeline = PaddleOCRVL(
    pipeline_version="v1.5",
    vl_rec_model_name="PaddleOCR-VL-1.5-0.9B",
    layout_detection_model_name="PP-DocLayoutV3",
    use_doc_orientation_classify=True,
    use_doc_unwarping=True,
)
R["load_model_s"] = mark("load PaddleOCRVL", t)

t = time.perf_counter()
res = list(pipeline.predict(PRE))[0]
R["predict_s"] = mark("predict 1 trang", t)
data = res.json.get("res", res.json)
R["regions"] = len(data.get("parsing_res_list") or [])
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=2)
print("[par] client", json.dumps(R, ensure_ascii=False), flush=True)
'''


def log(msg: str) -> None:
    print(f"[par] {msg}", flush=True)


def run(cmd, **kw) -> tuple[int, float]:
    t = time.perf_counter()
    rc = subprocess.run(cmd, check=False, **kw).returncode
    return rc, round(time.perf_counter() - t, 2)


def stage1_no_paddle() -> dict:
    """Chạy trong kernel python, KHÔNG cần paddle: rasterize + preprocess + u2net + rembg cả trang."""
    S: dict = {}
    rc, dt = run([sys.executable, "-m", "pip", "install", "-q",
                  "pymupdf", "rembg[cpu]", "pillow", "numpy", "opencv-python-headless"])
    S["pip_stage1_s"] = dt

    t = time.perf_counter()
    import cv2
    import fitz
    import numpy as np
    from PIL import Image
    S["import_stage1_s"] = round(time.perf_counter() - t, 2)

    urllib.request.urlretrieve(IMAGE_URL, PNG)
    doc = fitz.open()
    rect = fitz.open(PNG)[0].rect
    doc.new_page(width=rect.width, height=rect.height).insert_image(
        fitz.Rect(0, 0, rect.width, rect.height), filename=PNG
    )
    doc.save(PDF)

    # rasterize 200dpi (bản production)
    t = time.perf_counter()
    doc = fitz.open(PDF)
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    raw = pix.tobytes("png")
    open("/tmp/par_raw.png", "wb").write(raw)
    S["rasterize_s"] = mark_into("rasterize", t, S)

    # preprocess cv2 verbatim (deskew + shadow + resize MAX_SIDE=2500)
    t = time.perf_counter()
    img = cv2.imread("/tmp/par_raw.png")

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

    def remove_shadow(bgr):
        chans = []
        for c in cv2.split(bgr):
            dil = cv2.dilate(c, np.ones((7, 7), np.uint8))
            bg = cv2.medianBlur(dil, 21)
            chans.append(cv2.normalize(255 - cv2.absdiff(c, bg), None, 0, 255,
                                       cv2.NORM_MINMAX))
        return cv2.merge(chans)

    angle = estimate_skew(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    if abs(angle) >= 0.3:
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
    img = remove_shadow(img)
    h, w = img.shape[:2]
    if max(h, w) > 2500:
        s = 2500 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(PRE, img)
    S["preprocess_s"] = mark_into("preprocess", t, S)

    # u2net download + rembg CẢ TRANG (không cần bbox)
    t = time.perf_counter()
    from rembg import new_session, remove
    sess = new_session()
    S["u2net_session_s"] = mark_into("u2net new_session (tải nếu chưa có)", t, S)

    t = time.perf_counter()
    with open(PNG, "rb") as f:
        full = f.read()
    remove(full, session=sess)
    S["rembg_full_page_s"] = mark_into("rembg cả trang", t, S)
    return S


def mark_into(name: str, t0: float, S: dict) -> float:
    dt = round(time.perf_counter() - t0, 2)
    print(f"[par] stage1 {name}: {dt}s", flush=True)
    return dt


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    R: dict = {"gpu": subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True, check=False).stdout.strip(),
        "n_gpu": len(subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True,
            check=False).stdout.strip().splitlines())}
    R["uv_preinstalled"] = shutil.which("uv") is not None
    log(f"GPU: {R['gpu']!r} n={R['n_gpu']} uv_preinstalled={R['uv_preinstalled']}")
    t_all = time.perf_counter()

    if not R["uv_preinstalled"]:
        rc, dt = run([sys.executable, "-m", "pip", "install", "-q", "uv"])
        R["pip_uv_s"] = dt
    else:
        R["pip_uv_s"] = 0.0
    os.environ["PATH"] += os.pathsep + os.path.expanduser("~/.local/bin")

    t = time.perf_counter()
    run(["uv", "venv", VENV, "--python", "3.12"])
    py = os.path.join(VENV, "bin", "python")
    R["venv_s"] = mark_into("venv", t, R)

    # ---- SONG SONG: pip paddle (Popen) ∥ stage-1 (không cần paddle) ----
    t = time.perf_counter()
    proc = subprocess.Popen(
        ["uv", "pip", "install", "-p", py, "paddlepaddle-gpu==3.2.1",
         "--extra-index-url", PADDLE_IDX],
        stdout=open("/tmp/par_pip.log", "w"), stderr=subprocess.STDOUT,
    )
    log("paddle install chạy nền (Popen)")
    S1 = stage1_no_paddle()
    R["stage1"] = S1
    R["stage1_wall_s"] = round(time.perf_counter() - t, 2)
    rc = proc.wait()
    R["pip_paddle_rc"] = rc
    R["pip_paddle_wall_s"] = round(time.perf_counter() - t, 2)
    log(f"stage1 {R['stage1_wall_s']}s ∥ pip paddle {R['pip_paddle_wall_s']}s (rc={rc})")
    R["overlap_saved_s"] = round(
        R["pip_paddle_wall_s"] + R["stage1_wall_s"] - max(
            R["pip_paddle_wall_s"], R["stage1_wall_s"]), 2)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)

    rc, dt = run(["uv", "pip", "install", "-p", py, "paddleocr[doc-parser]>=3.6.0",
                  "safetensors"])
    R["pip_rest_s"] = dt

    open("/tmp/par_client.py", "w", encoding="utf-8").write(CLIENT_SRC)
    t = time.perf_counter()
    run([py, "/tmp/par_client.py", PRE, "/tmp/par_client.json"])
    R["client_wall_s"] = round(time.perf_counter() - t, 2)
    try:
        R.update(json.load(open("/tmp/par_client.json")))
    except Exception as exc:
        R["client_error"] = f"{type(exc).__name__}: {exc}"

    R["total_wall_s"] = round(time.perf_counter() - t_all, 2)
    # chuỗi tuần tự tương đương = tổng các phần (không chồng)
    serial = (R["pip_uv_s"] + R["venv_s"] + R["pip_paddle_wall_s"] + R.get("pip_rest_s", 0)
              + R.get("import_base_s", 0) + R.get("import_paddle_s", 0)
              + R.get("load_model_s", 0) + R.get("predict_s", 0)
              + S1.get("pip_stage1_s", 0) + S1.get("import_stage1_s", 0)
              + S1.get("rasterize_s", 0) + S1.get("preprocess_s", 0)
              + S1.get("u2net_session_s", 0) + S1.get("rembg_full_page_s", 0))
    R["serial_equivalent_s"] = round(serial, 2)
    R["speedup"] = round(serial / R["total_wall_s"], 2) if R["total_wall_s"] else None

    log(json.dumps(R, ensure_ascii=False))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
