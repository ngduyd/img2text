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
    subprocess.run(
        [
            "curl", "-Ls", "https://micro.mamba.pm/api/micromamba/linux-64/latest",
            "|", "tar", "-xj", "-C", os.path.dirname(mmamba), "--strip-components=1",
        ],
        check=True,
        shell=True,
    )
    return mmamba


def create_env(mmamba: str) -> None:
    """Create conda env with img2text deps."""
    run([
        mmamba, "create", "-y", "-p", ENV_PREFIX,
        "-c", "conda-forge",
    ] + DEPS)


def pack_env(mmamba: str) -> None:
    """Pack env into tarball."""
    os.makedirs(os.path.dirname(OUTPUT_TAR), exist_ok=True)
    run([
        mmamba, "pack", "-p", ENV_PREFIX,
        "-o", OUTPUT_TAR,
        "--compress-level", "9",
    ])


def upload_dataset() -> None:
    """Upload tarball to Kaggle Dataset."""
    os.environ.setdefault("KAGGLE_CONFIG_DIR", os.path.expanduser("~/.kaggle"))
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    # Create dataset if not exists
    try:
        api.dataset_create_new(
            slug=DATASET_SLUG.split("/")[1],
            title="img2text-env",
            is_private=True,
        )
    except Exception as e:
        print(f"dataset create (may already exist): {e}")

    # Upload files as new version
    api.dataset_create_version(
        folder=os.path.dirname(OUTPUT_TAR),
        version_notes="img2text env",
        dataset_slug=DATASET_SLUG,
    )


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
