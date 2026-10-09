#!/usr/bin/env python3
"""wheeltest: spike — cài wheels từ Dataset jhandf/img2text-wheels (no-index) → verify → OCR smoke.

So sánh timing với envtest (unpack conda env). Throwaway.
Cần wheelbuild đã chạy + Dataset img2text-wheels tồn tại.
"""

import glob
import json
import os
import subprocess
import sys
import time

WHEELS_GLOB = "/kaggle/input/img2text-wheelbuild-env/**/*.whl"
VENV = "/tmp/paddle-venv"
PY = os.path.join(VENV, "bin", "python")
DEPS = [
    "pillow", "numpy", "opencv-python-headless", "rapidfuzz", "pymupdf",
    "paddlepaddle-gpu", "paddleocr",
]
report: dict = {"wheels_found": 0, "install_s": None, "verify_s": None,
                "ocr_s": None, "ok": False, "errors": []}

VERIFY_CODE = (
    "import sys, numpy, cv2; import paddle, paddleocr, fitz; "
    "print('python', sys.version.split()[0]); "
    "print('paddle', paddle.__version__, 'cuda', paddle.is_compiled_with_cuda()); "
    "print('VERIFY_OK')"
)
OCR_CODE = """
import json, time
from PIL import Image, ImageDraw
img = Image.new("RGB", (640, 120), "white")
ImageDraw.Draw(img).text((20, 40), "IMG2TEXT WHEEL TEST 12345", fill="black")
img.save("/tmp/smoke.png")
t0 = time.time()
try:
    from paddleocr import PaddleOCR
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="en", use_gpu=False, show_log=False)
        r = ocr.ocr("/tmp/smoke.png")
    except TypeError:
        ocr = PaddleOCR(lang="en", device="cpu")
        r = list(ocr.predict("/tmp/smoke.png"))
    texts = []
    for page in (r if isinstance(r, list) else []):
        if not page:
            continue
        for item in (page if isinstance(page, list) else [page]):
            try:
                texts.append(str(item[1][0]))
            except (TypeError, IndexError):
                texts.append(str(item))
    print(json.dumps({"ocr_s": round(time.time() - t0, 2), "texts": texts[:5]}))
    print("OCR_OK")
except Exception as e:
    print(json.dumps({"ocr_s": round(time.time() - t0, 2), "error": repr(e)}))
    sys.exit(2)
"""


def find_wheel_dir() -> str:
    hits = glob.glob(WHEELS_GLOB, recursive=True)
    if not hits:
        raise SystemExit(f"không thấy wheel nào: {WHEELS_GLOB} — chạy wheelbuild + tạo Dataset trước")
    d = os.path.dirname(hits[0])
    # có thể wheels nằm dưới subdir owner/slug/wheels
    while d != "/kaggle/input" and not glob.glob(os.path.join(d, "*.whl")):
        d = os.path.dirname(d)
    return d


def main() -> int:
    print("=== wheeltest spike ===", flush=True)
    wdir = find_wheel_dir()
    n = len(glob.glob(os.path.join(wdir, "*.whl")))
    report["wheels_found"] = n
    print(f"wheel dir: {wdir} ({n} whl)", flush=True)

    # uv + venv py3.12 (kaggle py3.13 ko có paddle wheel) — network chỉ để có uv+python
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=False)
    t0 = time.time()
    subprocess.run(["uv", "venv", VENV, "--python", "3.12"], check=True)
    print(f"venv ready ({time.time()-t0:.1f}s)", flush=True)

    t0 = time.time()
    r = subprocess.run(
        ["uv", "pip", "install", "--python", PY, "--no-index",
         "--find-links", wdir, *DEPS],
        capture_output=True, text=True,
    )
    report["install_s"] = round(time.time() - t0, 2)
    print(r.stdout[-1500:], flush=True)
    if r.returncode != 0:
        report["errors"].append(f"install: {r.stderr[-800:]}")
        print(f"INSTALL FAIL: {r.stderr[-800:]}", flush=True)
        print("REPORT " + json.dumps(report), flush=True)
        return 1

    t0 = time.time()
    v = subprocess.run([PY, "-c", VERIFY_CODE], capture_output=True, text=True)
    report["verify_s"] = round(time.time() - t0, 2)
    print(v.stdout, flush=True)
    if "VERIFY_OK" not in v.stdout:
        report["errors"].append(f"verify: {v.stderr[-500:]}")
    else:
        t0 = time.time()
        o = subprocess.run([PY, "-c", OCR_CODE], capture_output=True, text=True)
        report["ocr_s"] = round(time.time() - t0, 2)
        print(o.stdout, flush=True)
        if "OCR_OK" not in o.stdout:
            report["errors"].append(f"ocr: {o.stderr[-500:] or o.stdout[-300:]}")

    report["ok"] = not report["errors"]
    report["total_s"] = round((report["install_s"] or 0) + (report["verify_s"] or 0)
                              + (report["ocr_s"] or 0), 2)
    print("REPORT " + json.dumps(report), flush=True)
    print(f"=== done ok={report['ok']} total={report['total_s']}s ===", flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
