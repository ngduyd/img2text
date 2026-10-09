#!/usr/bin/env python3
"""
img2text-env builder — chạy trên Kaggle Kernel để build env + upload Dataset.

First-run vs subsequent-runs:
  - First-run: dataset chưa tồn tại trên Kaggle → script tạo env, pack tar.gz,
    gọi dataset_create_new() để tạo Dataset mới, rồi dataset_create_version().
  - Subsequent-runs: dataset đã tồn tại → script rebuild env, pack tar.gz,
    chỉ gọi dataset_create_version() để push version mới.
  - Nếu API trả 403 (forbidden) → raise ngay, không silent-catch.

Runtime usage (img2text_batch.py):
    import tarfile, os
    with tarfile.open("/kaggle/input/img2text-env/img2text-env.tar.gz") as tf:
        tf.extractall("/kaggle/working/env")
    os.environ["PATH"] = "/kaggle/working/env/bin:" + os.environ["PATH"]
"""

import json
import os
import shutil
import subprocess
import sys

ENV_PREFIX = "/kaggle/working/env"
OUTPUT_TAR = "/kaggle/working/img2text-env-dataset/img2text-env.tar.gz"
DATASET_SLUG = "jhandf/img2text-env"
UPLOAD_DIR = "/kaggle/working/img2text-env-dataset"

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


def get_http_status(exc: Exception) -> int | None:
    """Extract HTTP status code from a Kaggle API exception."""
    # KaggleApi wraps HTTPError; check common attributes
    for attr in ("status", "status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    # HTTPError has .code or .response.status_code
    response = getattr(exc, "response", None)
    if response is not None:
        return getattr(response, "status_code", None)
    return None


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


def verify_imports() -> None:
    """Verify critical packages are importable in the built env."""
    python = os.path.join(ENV_PREFIX, "bin", "python")
    check_script = (
        "import numpy, cv2, paddle, paddleocr; "
        "print('imports OK')"
    )
    run([python, "-c", check_script])


def cleanup_upload_dir() -> None:
    """Remove stale files from upload dir before copying new artifacts."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    for name in ("dataset-metadata.json",):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.exists(path):
            os.remove(path)
            print(f"removed stale: {path}", flush=True)


def write_metadata() -> None:
    """Write dataset-metadata.json with license 'other' (bundled third-party env)."""
    metadata = {
        "id": DATASET_SLUG,
        "title": "img2text-env",
        "licenses": [{"name": "other"}],
    }
    metadata_path = os.path.join(UPLOAD_DIR, "dataset-metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"wrote {metadata_path}", flush=True)


def upload_dataset(api) -> None:
    """Upload to Kaggle: create if new, else push new version."""
    # Check if dataset already exists
    try:
        api.dataset_view(DATASET_SLUG)
        dataset_exists = True
        print(f"dataset {DATASET_SLUG} exists → will create new version", flush=True)
    except Exception as e:
        status = get_http_status(e)
        if status == 404:
            dataset_exists = False
            print(f"dataset {DATASET_SLUG} not found (404) → will create new", flush=True)
        elif status == 403:
            raise RuntimeError(
                f"403 Forbidden accessing {DATASET_SLUG}. "
                "Check Kaggle credentials / dataset permissions."
            ) from e
        else:
            raise

    if not dataset_exists:
        api.dataset_create_new(
            folder=UPLOAD_DIR,
            public=False,
        )
        print("dataset created (initial version)", flush=True)
    else:
        api.dataset_create_version(
            folder=UPLOAD_DIR,
            version_notes="img2text env",
        )
        print("version created", flush=True)


def _main() -> int:
    print("=== img2text env builder ===", flush=True)

    mmamba = ensure_micromamba()
    print(f"micromamba: {mmamba}", flush=True)

    # 0. Remove old env to avoid stale deps
    if os.path.exists(ENV_PREFIX):
        print(f"removing old env: {ENV_PREFIX}", flush=True)
        shutil.rmtree(ENV_PREFIX)

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

    # 2.5 Verify imports
    verify_imports()

    # 3. Prepare upload dir, then pack (faster, no micromamba pack bugs)
    cleanup_upload_dir()
    run(["tar", "-czf", OUTPUT_TAR, "-C", ENV_PREFIX, "."])
    size_mb = os.path.getsize(OUTPUT_TAR) / 1024 / 1024
    if size_mb < 1:
        raise RuntimeError(f"archive too small ({size_mb:.1f} MB) — build likely failed")
    print(f"packed: {OUTPUT_TAR} ({size_mb:.1f} MB)", flush=True)

    # 4. Write metadata
    write_metadata()

    # 5. Upload to Kaggle
    os.environ.setdefault("KAGGLE_CONFIG_DIR", "/root/.kaggle")
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    upload_dataset(api)
    print(f"uploaded to Kaggle Dataset: {DATASET_SLUG}", flush=True)

    print("=== done ===", flush=True)
    return 0

def main() -> int:
    try:
        return _main()
    finally:
        # Cleanup even on failure → Save Version won't pack thousands of files
        shutil.rmtree(ENV_PREFIX, ignore_errors=True)
        shutil.rmtree("/kaggle/working/micromamba", ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
