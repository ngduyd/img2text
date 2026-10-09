#!/usr/bin/env python3
"""
Kaggle notebook script: đóng gói env + save vào Kaggle Dataset.

Chạy trong Kaggle notebook (GPU instance):
    !python3 build_env_kaggle.py

Hoặc paste vào cell:
    !pip install micromamba  # or use system conda
    !conda create -y -p /kaggle/working/env python=3.10 pillow numpy opencv rapidfuzz pymupdf paddlepaddle-gpu paddleocr
    !tar -czf /kaggle/working/img2text-env.tar.gz -C /kaggle/working/env .
    # Upload via Kaggle UI or API
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
    "paddlepaddle-gpu",
    "paddleocr",
]


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def create_env() -> None:
    """Create env using system conda (Kaggle has conda pre-installed)."""
    run([
        "conda", "create", "-y", "-p", ENV_PREFIX,
        "-c", "conda-forge",
    ] + DEPS)


def pack_env() -> None:
    """Pack env into tarball."""
    run([
        "tar", "-czf", OUTPUT_TAR,
        "-C", ENV_PREFIX, ".",
    ])
    size_mb = os.path.getsize(OUTPUT_TAR) / 1024 / 1024
    print(f"packed: {OUTPUT_TAR} ({size_mb:.1f} MB)", flush=True)


def upload_dataset() -> None:
    """Upload tarball to Kaggle Dataset."""
    os.environ.setdefault("KAGGLE_CONFIG_DIR", "/root/.kaggle")
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
    print("=== img2text env builder (Kaggle) ===", flush=True)

    create_env()
    print("env created", flush=True)

    pack_env()
    print("env packed", flush=True)

    upload_dataset()
    print(f"uploaded to Kaggle Dataset: {DATASET_SLUG}", flush=True)

    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
