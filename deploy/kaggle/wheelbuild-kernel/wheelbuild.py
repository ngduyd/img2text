#!/usr/bin/env python3
"""wheelbuild: download wheels cp312 manylinux cho batch OCR deps → /kaggle/working/wheels.

Run 1 lần → Save Version → Create Dataset từ Output (tên gợi ý:
jhandf/img2text-wheels). Kernel wheeltest install --no-index từ đó.
"""

import glob
import os
import subprocess
import sys

DEPS = [
    "pillow", "numpy", "opencv-python-headless", "rapidfuzz", "pymupdf",
    # recipe đã chạy được (Colab): paddle 3.2.1 cu126 + paddleocr[doc-parser]
    "paddlepaddle-gpu==3.2.1", "paddleocr[doc-parser]>=3.6.0",
    "safetensors", "tokenizers==0.22.2", "huggingface-hub>=0.25.0,<1.0",
]
# paddle GPU wheel KHÔNG có trên PyPI → index cu126 chính thức
PADDLE_CU126 = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"
WHEELS = "/kaggle/working/wheels"


def main() -> int:
    print("=== wheelbuild ===", flush=True)
    os.makedirs(WHEELS, exist_ok=True)

    # uv: nhanh hơn pip cho download; fallback pip
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=False)
    uv = subprocess.run(["which", "uv"], capture_output=True, text=True).stdout.strip()
    cmd_base = [uv, "pip", "download"] if uv else [sys.executable, "-m", "pip", "download"]

    cmd = cmd_base + [
        "-d", WHEELS,
        "--python-version", "3.12",
        "--only-binary", ":all:",
        "--platform", "manylinux2014_x86_64",
        "--platform", "manylinux_2_17_x86_64",
        "--implementation", "cp",
        "--extra-index-url", PADDLE_CU126,
        *DEPS,
    ]
    # uv pip download không có --platform flags → dùng pip cho cross-version
    if uv:
        cmd = [sys.executable, "-m", "pip", "download"] + cmd[cmd.index("-d"):]
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-2000:])
    if r.returncode != 0:
        print("STDERR:", r.stderr[-2000:], flush=True)
        return 1

    wheels = sorted(glob.glob(os.path.join(WHEELS, "*.whl")))
    total_mb = sum(os.path.getsize(w) for w in wheels) / 1e6
    print(f"\nwheels: {len(wheels)} files, {total_mb:.0f} MB", flush=True)
    for w in wheels:
        print(f"  {os.path.basename(w)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
