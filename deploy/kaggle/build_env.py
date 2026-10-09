#!/usr/bin/env python3
"""
Build conda env for img2text + pack + upload Kaggle Dataset.

Usage (run once in Kaggle notebook or locally with Kaggle credentials):
    python3 build_env.py

Output:
    Kaggle Dataset: jhandf/img2text-env (img2text-env.tar.gz)

Then in img2text_batch.py:
    import tarfile, os
    with tarfile.open("/kaggle/input/img2text-env/img2text-env.tar.gz") as tf:
        tf.extractall("/kaggle/working/env")
    os.environ["PATH"] = "/kaggle/working/env/bin:" + os.environ["PATH"]
"""

import json
import os
import subprocess
import sys

ENV_NAME = "img2text"
ENV_PREFIX = os.path.expanduser(f"~/micromamba/envs/{ENV_NAME}")
OUTPUT_TAR = "/tmp/img2text-env.tar.gz"
DATASET_SLUG = "jhandf/img2text-env"

CONDA_DEPS = [
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
    mmamba = os.path.expanduser("~/bin/micromamba")
    if os.path.exists(mmamba):
        return mmamba
    os.makedirs(os.path.dirname(mmamba), exist_ok=True)
    tarball = "/tmp/micromamba.tar.bz2"
    subprocess.run(
        ["curl", "-Ls", "-o", tarball, "https://micro.mamba.pm/api/micromamba/linux-64/latest"],
        check=True,
    )
    import tarfile
    with tarfile.open(tarball, "r:bz2") as tf:
        tf.extractall(os.path.expanduser("~"))
    # micromamba at bin/micromamba
    return os.path.join(os.path.expanduser("~"), "bin", "micromamba")


def create_env(mmamba: str) -> None:
    """Create conda env with img2text deps."""
    run([
        mmamba, "create", "-y", "-p", ENV_PREFIX,
        "-c", "conda-forge",
    ] + CONDA_DEPS)
    # paddle not in conda-forge → pip install
    pip_path = os.path.join(ENV_PREFIX, "bin", "pip")
    run([pip_path, "install"] + PIP_DEPS)


def pack_env(mmamba: str) -> None:
    """Pack env into tarball."""
    run([
        mmamba, "package", "compress", ENV_PREFIX, OUTPUT_TAR,
    ])


def upload_dataset() -> None:
    """Upload tarball to Kaggle Dataset."""
    os.environ.setdefault("KAGGLE_CONFIG_DIR", os.path.expanduser("~/.kaggle"))
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    # Prepare upload folder with metadata + tarball
    upload_dir = os.path.expanduser("~/kaggle_upload")
    os.makedirs(upload_dir, exist_ok=True)
    metadata = {"id": DATASET_SLUG, "title": "img2text-env", "licenses": [{"name": "MIT"}]}
    with open(f"{upload_dir}/dataset-metadata.json", "w") as f:
        json.dump(metadata, f)
    import shutil
    shutil.copy(OUTPUT_TAR.replace('.gz', '.bz2'), upload_dir)

    # Create dataset if not exists
    try:
        api.dataset_create_new(folder=upload_dir, public=False)
        print("dataset created")
    except Exception as e:
        print(f"dataset create (may already exist): {e}")

    # Upload files as new version
    try:
        api.dataset_create_version(
            folder=upload_dir,
            version_notes="img2text env",
        )
        print("version uploaded")
    except Exception as e:
        print(f"version upload failed: {e}")


def main() -> int:
    print("=== img2text env builder ===", flush=True)

    mmamba = ensure_micromamba()
    print(f"micromamba: {mmamba}", flush=True)

    create_env(mmamba)
    print("env created", flush=True)

    pack_env(mmamba)
    size_mb = os.path.getsize(OUTPUT_TAR) / 1024 / 1024
    print(f"packed: {OUTPUT_TAR} ({size_mb:.1f} MB)", flush=True)

    upload_dataset()
    print(f"uploaded to Kaggle Dataset: {DATASET_SLUG}", flush=True)

    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
