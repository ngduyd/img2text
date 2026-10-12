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
    "rembg",
]
# u2net.onnx (rembg model ~170MB) — download 1 lần vào wheels/ → dataset
# wheelbuild-env; kernel set U2NET_HOME vào dir này (không tải lại mỗi run).
U2NET_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
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

    # uv venv không kèm pip + không ensurepip → bootstrap pip qua uv
    subprocess.run(
        ["uv", "pip", "install", "--python", py, "pip"],
        check=False,
    )

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

    # u2net.onnx model → wheels/ (dataset upload 1 lần, kernel U2NET_HOME đọc)
    model = os.path.join(WHEELS, "u2net.onnx")
    if not os.path.exists(model):
        print(f"download {U2NET_URL}", flush=True)
        code = (
            "import sys, urllib.request; "
            "urllib.request.urlretrieve(sys.argv[1], sys.argv[2])"
        )
        r = subprocess.run(
            [py, "-c", code, U2NET_URL, model], capture_output=True, text=True
        )
        if r.returncode != 0:
            print("u2net download fail (rembg sẽ tự tải lúc dùng):", r.stderr[-500:], flush=True)
    print(f"u2net: {os.path.exists(model)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
