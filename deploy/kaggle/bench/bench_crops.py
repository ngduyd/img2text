"""Bench ẩn số cuối: crops + rembg (u2net) — stage duy nhất chưa đo của luồng production.

Production `extract_crops` (`img2text_batch.py:1035-1078`) làm 2 việc cho MỖI image block:
  1. `page.get_pixmap(clip=fitz.Rect(bbox đã scale), matrix=fitz.Matrix(2,2))` (144dpi) + PNG encode
  2. `rembg.remove(png)` — u2net CPU
Chưa ai đo 2 việc này. Cũng chưa đo chi phí `new_session()` (tải u2net.onnx ~176MB nếu không có
sẵn trong /kaggle/input — production có cache trong wheelbuild dataset).

Không cài paddle (không cần): chỉ pymupdf + rembg → kernel nhanh, không đụng torch/nccl.
Đo: pip, dựng PDF 1 trang, fitz clip ở 3 kích thước crop, rembg session + remove ở 3 kích thước.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

IMAGE_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/"
    "paddleocr_vl_demo.png"
)
OUT = "/kaggle/working/bench_crops_result.json"
SIZES = [256, 512, 1024]

CLIENT_SRC = r'''
import json, sys, time
import numpy as np
from PIL import Image
import fitz

PDF, OUT, SIZES = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
R = {}
def mark(name, t0, extra=None):
    dt = round(time.perf_counter() - t0, 2)
    print(f"[crops] {name}: {dt}s" + (f" {extra}" if extra else ""), flush=True)
    return dt

doc = fitz.open(PDF)
page = doc[0]

t = time.perf_counter()
base = page.get_pixmap(dpi=200)
R["pixmap_full_page_s"] = mark("pixmap full page 200dpi", t,
                               f"{base.width}x{base.height}")

def clip_png(side):
    cx, cy = page.rect.width / 2, page.rect.height / 2
    half_w, half_h = side / 2, side / 2
    clip = fitz.Rect(cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2))  # 144dpi như prod
    return pix.tobytes("png")

R["fitz_clip"] = {}
R["rembg"] = {}
for side in SIZES:
    ts = []
    data = b""
    for _ in range(3):
        t = time.perf_counter()
        data = clip_png(side)
        ts.append(round(time.perf_counter() - t, 3))
    R["fitz_clip"][side] = ts
    mark(f"fitz clip {side}px x3", time.perf_counter() - sum(ts), f"{len(data)}B")

t = time.perf_counter()
from rembg import new_session, remove
sess = new_session()
R["rembg_session_s"] = mark("rembg new_session (tải u2net nếu chưa cache)", t)

for side in SIZES:
    png = clip_png(side)
    ts = []
    for _ in range(3):
        t = time.perf_counter()
        remove(png, session=sess)
        ts.append(round(time.perf_counter() - t, 3))
    R["rembg"][side] = ts
    mark(f"rembg remove {side}px x3", sum(ts))

t = time.perf_counter()
remove(clip_png(512), session=sess)
R["rembg_warm_512_s"] = mark("rembg remove 512px warm", t)

json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=2)
print("[crops] RESULT", json.dumps(R, ensure_ascii=False), flush=True)
'''


def log(msg: str) -> None:
    print(f"[crops] {msg}", flush=True)


def run(cmd, **kw) -> int:
    log("$ " + " ".join(map(str, cmd)))
    return subprocess.run(cmd, check=False, **kw).returncode


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    result: dict = {"gpu": subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True, check=False).stdout.strip()}

    t = time.perf_counter()
    run([sys.executable, "-m", "pip", "install", "-q",
         "pymupdf", "rembg[cpu]", "pillow", "numpy"])
    result["pip_s"] = round(time.perf_counter() - t, 2)
    log(f"pip: {result['pip_s']}s")

    t = time.perf_counter()
    urllib.request.urlretrieve(IMAGE_URL, "/tmp/crop_page.png")
    import fitz  # noqa: PLC0415
    doc = fitz.open()
    rect = fitz.open("/tmp/crop_page.png")[0].rect
    doc.new_page(width=rect.width, height=rect.height).insert_image(
        fitz.Rect(0, 0, rect.width, rect.height), filename="/tmp/crop_page.png"
    )
    doc.save("/tmp/crop_1p.pdf")
    result["make_pdf_s"] = round(time.perf_counter() - t, 2)
    log(f"PDF 1 trang: {os.path.getsize('/tmp/crop_1p.pdf')}B")

    open("/tmp/crops_client.py", "w", encoding="utf-8").write(CLIENT_SRC)
    t = time.perf_counter()
    run([sys.executable, "/tmp/crops_client.py", "/tmp/crop_1p.pdf", "/tmp/crops.json",
         json.dumps(SIZES)])
    result["client_wall_s"] = round(time.perf_counter() - t, 2)
    try:
        result.update(json.load(open("/tmp/crops.json")))
    except Exception as exc:
        result["client_error"] = f"{type(exc).__name__}: {exc}"

    log(json.dumps(result, ensure_ascii=False))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
