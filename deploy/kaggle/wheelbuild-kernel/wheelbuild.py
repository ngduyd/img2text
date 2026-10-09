#!/usr/bin/env python3
"""wheelbuild: download wheels cp312 cho batch OCR deps → /kaggle/working/wheels.

Tạo venv py3.12 (khớp target venv) rồi pip download TỪ venv đó → native
cp312 wheels, KHÔNG filter --platform (tránh loại paddle wheel tag
manylinux_2_28 như cách cross-download). Giống cách Colab install.
Recipe paddle: 3.2.1 từ cu126 index.
"""

import glob
import os
import subprocess
import sys

DEPS = [
    "pillow", "numpy", "opencv-python-headless", "rapidfuzz", "pymupdf",
    "paddlepaddle-gpu==3.2.1", "paddleocr[doc-parser]>=3.6.0",
    "safetensors", "tokenizers==0.22.2", "huggingface-hub>=0.25.0,<1.0",
]
PADDLE_CU126 = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"
WHEELS = "/kaggle/working/wheels"
DL_VENV = "/tmp/dl-py312"


def main() -> int:
    print("=== wheelbuild ===", flush=True)
    os.makedirs(WHEELS, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=False)

    # venv py3.12 = target python → download native cp312, không cần --platform
    subprocess.run(["uv", "venv", DL_VENV, "--python", "3.12"], check=True)
    py = os.path.join(DL_VENV, "bin", "python")

    # ensure pip trong venv (uv venv không kèm pip)
    subprocess.run([py, "-m", "ensurepip", "-q"], check=False)
    subprocess.run([py, "-m", "pip", "install", "-q", "pip"], check=False)

    cmd = [
        py, "-m", "pip", "download", "-d", WHEELS,
        "--only-binary", ":all:",
        "--extra-index-url", PADDLE_CU126,
        *DEPS,
    ]
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-2000:])
    if r.returncode != 0:
        print("STDERR:", r.stderr[-2000:], flush=True)
        return 1

    wheels = sorted(glob.glob(os.path.join(WHEELS, "*.whl")))
    total_mb = sum(os.path.getsize(w) for w in wheels) / 1e6
    ppdl = [os.path.basename(w) for w in wheels if "paddlepaddle" in os.path.basename(w)]
    print(f"\nwheels: {len(wheels)} files, {total_mb:.0f} MB", flush=True)
    print(f"paddle: {ppdl}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
