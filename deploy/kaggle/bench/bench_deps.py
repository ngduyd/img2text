"""Bench #4: (a) wheelhouse dataset vs pip network, (b) u2net cache, (c) rembg cả trang vs từng vùng.

Kernel này MOUNT dataset `jhandf/img2text-wheelbuild-env` (138 wheels + u2net.onnx) để so với
đường cài mạng — đúng thứ kernel session mode đang thiếu (`kernel-session-metadata.json`
có `dataset_sources: []`).

(a) cùng 1 phiên, cùng bộ deps `WHEELHOUSE_DEPS` của production, 2 venv riêng:
    whl: uv pip install --no-index --find-links <mounted>/wheels
    net: uv pip install (mạng, kèm paddle index)
(b) u2net: new_session() với U2NET_HOME trỏ vào file .onnx có sẵn (cache) vs thư mục rỗng (tải)
(c) rembg: remove() 1 lần trên CẢ TRANG 2117×1900 vs 3 lần trên 3 vùng crop — cùng session warm
"""

import glob
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
OUT = "/kaggle/working/bench_deps_result.json"
DEPS = [  # verbatim WHEELHOUSE_DEPS (img2text_batch.py:231)
    "pillow", "numpy", "opencv-python-headless", "rapidfuzz",
    "pymupdf", "paddlepaddle-gpu==3.2.1", "paddleocr[doc-parser]>=3.6.0",
    "safetensors", "tokenizers==0.22.2", "huggingface-hub>=0.25.0,<1.0",
    "rembg[cpu]", "pillow-heif",
]
PADDLE_IDX = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"


def log(msg: str) -> None:
    print(f"[deps] {msg}", flush=True)


def run(cmd, **kw) -> tuple[int, float]:
    t = time.perf_counter()
    rc = subprocess.run(cmd, check=False, **kw).returncode
    return rc, round(time.perf_counter() - t, 2)


def venv(path: str) -> str:
    if not os.path.exists(os.path.join(path, "bin", "python")):
        run(["uv", "venv", path, "--python", "3.12"])
    return os.path.join(path, "bin", "python")


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    R: dict = {"deps_count": len(DEPS)}

    wheels = [d for d in glob.glob("/kaggle/input/**/wheels", recursive=True)
              if os.path.isdir(d)]
    R["wheelhouse_dir"] = wheels[0] if wheels else None
    R["wheelhouse_files"] = len(os.listdir(wheels[0])) if wheels else 0
    log(f"wheelhouse: {R['wheelhouse_dir']} ({R['wheelhouse_files']} files)")

    _, R["pip_uv_s"] = run([sys.executable, "-m", "pip", "install", "-q", "uv"])

    # ---------- (a) wheelhouse (no-index) ----------
    if wheels:
        py_whl = venv("/tmp/venv-whl")
        rc, dt = run(["uv", "pip", "install", "-p", py_whl, "--no-index",
                      "--find-links", wheels[0], *DEPS])
        R["whl_install_rc"] = rc
        R["whl_install_s"] = dt
        log(f"wheelhouse install: {dt}s (rc={rc})")
        rc2, dt2 = run([py_whl, "-c", "import paddleocr; print('ok')"])
        R["whl_import_paddleocr_s"] = dt2
        R["whl_import_rc"] = rc2
        log(f"wheelhouse import paddleocr: {dt2}s (rc={rc2})")

    # ---------- (a) network ----------
    py_net = venv("/tmp/venv-net")
    rc, dt = run(["uv", "pip", "install", "-p", py_net,
                  "paddlepaddle-gpu==3.2.1", "--extra-index-url", PADDLE_IDX])
    R["net_install_paddle_s"] = dt
    rc2, dt2 = run(["uv", "pip", "install", "-p", py_net, *DEPS])
    R["net_install_rest_s"] = dt2
    R["net_install_total_s"] = round(dt + dt2, 2)
    R["net_install_rc"] = rc2
    log(f"network install: {R['net_install_total_s']}s (rc={rc2})")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)

    # ---------- (b)+(c) rembg ----------
    client = "/tmp/deps_client.py"
    open(client, "w", encoding="utf-8").write(CLIENT_SRC)
    run([sys.executable, "-m", "pip", "install", "-q", "pymupdf", "rembg[cpu]",
         "pillow", "numpy"])
    cached = next((p for p in glob.glob("/kaggle/input/**/u2net.onnx", recursive=True)), None)
    R["u2net_found"] = cached
    R["u2net_size_mb"] = round(os.path.getsize(cached) / 1e6, 1) if cached else None
    urllib.request.urlretrieve(IMAGE_URL, "/tmp/deps_page.png")
    rc, dt = run([sys.executable, client, "/tmp/deps_page.png", "/tmp/deps.json",
                  cached or ""])
    R["client_wall_s"] = dt
    R["client_rc"] = rc
    try:
        R.update(json.load(open("/tmp/deps.json")))
    except Exception as exc:
        R["client_error"] = f"{type(exc).__name__}: {exc}"

    log(json.dumps(R, ensure_ascii=False))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)
    return 0


CLIENT_SRC = r'''
import json, os, shutil, sys, time
import numpy as np

PNG, OUT, CACHED = sys.argv[1], sys.argv[2], sys.argv[3]
R = {}
def mark(name, t0, extra=None):
    dt = round(time.perf_counter() - t0, 2)
    print(f"[deps] {name}: {dt}s" + (f" {extra}" if extra else ""), flush=True)
    return dt

import fitz
from PIL import Image
from rembg import new_session, remove

# ---- (b) u2net: cache có sẵn trong dataset vs tải mới ----
if CACHED:
    home = "/tmp/u2net-cached"
    os.makedirs(home, exist_ok=True)
    shutil.copyfile(CACHED, os.path.join(home, "u2net.onnx"))
    os.environ["U2NET_HOME"] = home
    t = time.perf_counter()
    sess = new_session()
    R["u2net_cached_s"] = mark("new_session (u2net có sẵn, copy local)", t)
else:
    sess = None
    R["u2net_cached_s"] = None

if sess is None:
    os.environ["U2NET_HOME"] = "/tmp/u2net-empty"
    os.makedirs("/tmp/u2net-empty", exist_ok=True)
    t = time.perf_counter()
    sess = new_session()
    R["u2net_download_s"] = mark("new_session (phải tải u2net)", t)
else:
    os.environ["U2NET_HOME"] = "/tmp/u2net-empty2"
    os.makedirs("/tmp/u2net-empty2", exist_ok=True)
    t = time.perf_counter()
    sess2 = new_session()
    R["u2net_download_s"] = mark("new_session (thư mục rỗng → tải)", t)
    sess = sess or sess2

# ---- (c) rembg: cả trang vs 3 vùng ----
page_png = open(PNG, "rb").read()
im = Image.open(PNG)
W, H = im.size
R["page_size"] = [W, H]

t = time.perf_counter()
remove(page_png, session=sess)
R["rembg_full_page_s"] = mark("rembg CẢ TRANG", t)

doc = fitz.open()
page = doc.new_page(width=W, height=H)
page.insert_image(page.rect, filename=PNG)
side = min(W, H) // 3
regions = []
for i, (cx, cy) in enumerate(((W * 0.25, H * 0.25), (W * 0.75, H * 0.25), (W * 0.5, H * 0.75))):
    clip = fitz.Rect(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
    png = page.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2)).tobytes("png")
    t = time.perf_counter()
    remove(png, session=sess)
    regions.append(mark(f"rembg VÙNG {i + 1} ({side}px)", t))
R["rembg_regions_s"] = regions
R["rembg_regions_total_s"] = round(sum(regions), 2)
print("[deps] so sánh:", json.dumps(R, ensure_ascii=False), flush=True)
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=2)
'''


if __name__ == "__main__":
    sys.exit(main())
