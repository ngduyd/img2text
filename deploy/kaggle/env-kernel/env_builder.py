#!/usr/bin/env python3
"""
img2text-env builder — chạy 1 lần trên Kaggle để setup env + save Dataset.

Sau khi chạy xong, img2text_batch.py chỉ cần:
    import tarfile, os
    with tarfile.open("/kaggle/input/img2text-env/img2text-env.tar.gz") as tf:
        tf.extractall("/kaggle/working/env")
    os.environ["PATH"] = "/kaggle/working/env/bin:" + os.environ["PATH"]
"""

import os
import subprocess
import sys

ENV_PREFIX = "/kaggle/working/env"
OUTPUT_TAR = "/kaggle/working/img2text-env.tar.gz"
DATASET_SLUG = "jhandf/img2text-env"

DEPS = [
    "python=3.10",
    "pillow",
    "numpy",
    "opencv",
    "rapidfuzz",
    "pymupdf",
    "pip",
]
PIP_DEPS = [
    "paddlepaddle-gpu",
    "paddleocr",
]


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def ensure_micromamba() -> str:
    """Install micromamba if not present, return path."""
    mmamba = "/kaggle/working/micromamba/bin/micromamba"
    if os.path.exists(mmamba):
        return mmamba
    os.makedirs(os.path.dirname(mmamba), exist_ok=True)
    subprocess.run(
        "curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | "
        "tar -xj -C /kaggle/working/micromamba",
        check=True,
        shell=True,
    )
    return mmamba


def main() -> int:
    print("=== img2text env builder ===", flush=True)

    mmamba = ensure_micromamba()
    print(f"micromamba: {mmamba}", flush=True)

    # 1. Create env (conda deps only)
    run([
        mmamba, "create", "-y", "-p", ENV_PREFIX,
        "-c", "conda-forge",
    ] + DEPS)
    print("env created", flush=True)

    # 2. Install paddlepaddle-gpu + paddleocr via pip
    pip = os.path.join(ENV_PREFIX, "bin", "pip")
    run([pip, "install", "-q"] + PIP_DEPS)
    print("pip deps installed", flush=True)

    # 2. Pack
    run(["tar", "-czf", OUTPUT_TAR, "-C", ENV_PREFIX, "."])
    size_mb = os.path.getsize(OUTPUT_TAR) / 1024 / 1024
    print(f"packed: {OUTPUT_TAR} ({size_mb:.1f} MB)", flush=True)

    # 2.5 Copy dataset-metadata.json to script folder (/kaggle/src/)
    import shutil
    # Tìm dataset-metadata.json trong git folder (deploy/kaggle/env-kernel/)
    metadata_src = None
    for candidate in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset-metadata.json"),
        "/kaggle/src/dataset-metadata.json",
        "/kaggle/working/dataset-metadata.json",
    ]:
        if os.path.exists(candidate):
            metadata_src = candidate
            break
    if metadata_src:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        shutil.copy(metadata_src, script_dir)
        print(f"copied dataset-metadata.json from {metadata_src} to {script_dir}", flush=True)
    else:
        print("WARNING: dataset-metadata.json not found", flush=True)

    # 3. Upload Dataset (folder = script_dir, chứa dataset-metadata.json)
    os.environ.setdefault("KAGGLE_CONFIG_DIR", "/root/.kaggle")
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    upload_folder = os.path.dirname(os.path.abspath(__file__))

    try:
        api.dataset_create_new(
            folder=upload_folder,
            public=False,
        )
    except Exception as e:
        print(f"dataset create (may already exist): {e}")

    api.dataset_create_version(
        folder=upload_folder,
        version_notes="img2text env",
    )
    print(f"uploaded to Kaggle Dataset: {DATASET_SLUG}", flush=True)

    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
