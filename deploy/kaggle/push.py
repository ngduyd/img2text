#!/usr/bin/env python3
"""Manual Kaggle push for the img2text worker (Plan K).

ponytail: manual push now; Kaggle<->cloud-storage sync = production follow-up.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import kcompat

DEPLOY_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEPLOY_DIR.parent.parent
FILES_DIR = DEPLOY_DIR / "files"
WORKER_DIR = REPO_ROOT / "worker"
DATASET_SLUG = "img2text-worker-files"
KERNEL_SLUG = "img2text-worker"
DEFAULT_ACCELERATOR = "NvidiaTeslaT4"
DEFAULT_TIMEOUT = 10800
POLL_INTERVAL = 30
SECRETS_REMINDER = (
    'Reminder — before the kernel runs, set Kaggle Secrets (Add-ons → Secrets): '
    '"BASE_URL" (public URL, no localhost) + "RUNNER_KEY". '
    "Quota: free tier ~30h GPU/week."
)

SECRETS_CELL = '''# Secrets — retry until both are set
import time
from kaggle_secrets import UserSecretsClient

SECRETS = UserSecretsClient()

while True:
    try:
        BASE_URL = SECRETS.get_secret("BASE_URL")
        RUNNER_KEY = SECRETS.get_secret("RUNNER_KEY")
        break
    except Exception:
        print("Set BASE_URL and RUNNER_KEY in Kaggle Secrets (Add-ons → Secrets)")
        time.sleep(5)

print("BASE_URL:", BASE_URL)
print("RUNNER_KEY: set (", len(RUNNER_KEY), "chars )")
'''

MOUNT_PATH = f"/kaggle/input/{DATASET_SLUG}"


def load_env():
    """Kaggle 2.x: KAGGLE_API_TOKEN (Bearer KGAT_, kaggle.com/settings/api)
    is the primary auth — kaggle's authenticate() reads the env var itself;
    legacy KAGGLE_USERNAME+KAGGLE_KEY still accepted. Username is always
    required (OWNER id in dataset/kernel metadata). Returns (user, key_or_empty)."""
    user = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    token = os.environ.get("KAGGLE_API_TOKEN", "").strip()
    if not user or not (key or token):
        sys.exit(
            "error: set KAGGLE_USERNAME + KAGGLE_API_TOKEN "
            "(khuyến nghị, kaggle.com/settings/api) hoặc "
            "KAGGLE_USERNAME+KAGGLE_KEY legacy. "
            "See deploy/kaggle/README.md."
        )
    return user, key


def copy_worker_files():
    for name in ("pipeline.py", "verdict.py"):
        shutil.copyfile(WORKER_DIR / name, FILES_DIR / name)


def _sub_owner(obj, owner):
    if isinstance(obj, str):
        return obj.replace("OWNER", owner)
    if isinstance(obj, list):
        return [_sub_owner(x, owner) for x in obj]
    if isinstance(obj, dict):
        return {k: _sub_owner(v, owner) for k, v in obj.items()}
    return obj


def build_kernel_metadata(owner, accelerator, dest):
    meta = json.loads((DEPLOY_DIR / "kernel" / "kernel-metadata.json").read_text(encoding="utf-8"))
    meta = _sub_owner(meta, owner)
    meta["machine_shape"] = accelerator
    meta["accelerator"] = accelerator
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def build_dataset_metadata(owner, dest):
    meta = json.loads((FILES_DIR / "dataset-metadata.json").read_text(encoding="utf-8"))
    meta["id"] = f"{owner}/{DATASET_SLUG}"
    # kaggle 2.2.4 requires [{"name": ...}] dicts; coerce old string shape
    meta["licenses"] = [
        lic if isinstance(lic, dict) else {"name": lic}
        for lic in meta.get("licenses", [])
    ]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def build_kernel_notebook(dest):
    """Build the Kaggle kernel notebook from worker/colab_notebook.ipynb.

    Adaptations: secrets cell google.colab -> kaggle_secrets UserSecretsClient
    retry loop; loop cell sys.path mount of the files dataset; markdown header
    Colab -> Kaggle.
    """
    nb = json.loads((WORKER_DIR / "colab_notebook.ipynb").read_text(encoding="utf-8"))
    for cell in nb["cells"]:
        src = "".join(cell["source"])
        if cell.get("cell_type") == "markdown":
            if "Colab GPU runner" in src:
                cell["source"] = src.replace(
                    "Colab GPU runner (Plan C)", "Kaggle GPU runner"
                ).splitlines(keepends=True)
            continue
        if "google.colab" in src:
            cell["source"] = SECRETS_CELL.splitlines(keepends=True)
        elif 'sys.path.insert(0, "worker")' in src:
            cell["source"] = src.replace(
                'sys.path.insert(0, "worker")',
                f'sys.path.insert(0, "{MOUNT_PATH}")',
            ).splitlines(keepends=True)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def push_dataset(api, owner, files_stage):
    ref = f"{owner}/{DATASET_SLUG}"
    print(f"dataset: create {ref}")
    try:
        kcompat.api_create_dataset(api, str(files_stage))
        print(f"dataset created: {ref}")
    except Exception as exc:
        print(f"dataset create failed or already exists ({exc}); bumping version")
        try:
            # new API versions FROM the staged folder (uploads files); legacy
            # takes (owner, slug) — kcompat splits the ref
            kcompat.api_version_dataset(api, files_stage, ref, "push.py manual")
            print(f"dataset version bumped: {ref}")
        except Exception as exc2:
            sys.exit(
                f"error: dataset version bump failed for {ref}: {exc2}\n"
                f"original create error: {exc}\n"
                f"hint: check dataset owner/slug on kaggle.com (slug must be {DATASET_SLUG})"
            )


def push_kernel(api, owner, kernel_dir, args):
    ref = f"{owner}/{KERNEL_SLUG}"
    print(f"kernel: push {ref}")
    try:
        api.kernels_push(
            str(kernel_dir),
            no_run=args.no_run,
            timeout=args.timeout,
            accelerator=args.accelerator,
        )
    except TypeError:
        # ponytail: old kaggle package without kernels_push kwargs
        print("note: kaggle package lacks push kwargs (no_run/timeout/accelerator); pushing as-is")
        api.kernels_push(str(kernel_dir))
    status = wait_for_kernel(api, ref)
    print(f"kernel {ref}: {status}")
    print(f"hint: kaggle kernels output {ref}")


def wait_for_kernel(api, ref):
    while True:
        resp = api.kernels_status(ref)
        status = resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None)
        if status in ("complete", "failed"):
            return status
        print(f"kernel {ref}: status={status} — polling every {POLL_INTERVAL}s")
        time.sleep(POLL_INTERVAL)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manual Kaggle push for the img2text worker (Plan K)")
    parser.add_argument("--no-run", action="store_true", help="push kernel without running it")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="kernel timeout seconds")
    parser.add_argument("--accelerator", default=DEFAULT_ACCELERATOR, help="GPU accelerator id")
    parser.add_argument("--skip-dataset", action="store_true", help="skip dataset create/version")
    args = parser.parse_args(argv)

    owner, _key = load_env()

    try:
        from kaggle import KaggleApi
    except ImportError:
        sys.exit("error: kaggle package missing — pip install kaggle")

    api = KaggleApi()
    api.authenticate()
    print(SECRETS_REMINDER)

    copy_worker_files()

    build_dir = Path(tempfile.mkdtemp(prefix="kaggle-img2text-build-"))
    try:
        files_stage = build_dir / "files"
        files_stage.mkdir()
        for name in ("pipeline.py", "verdict.py"):
            shutil.copyfile(FILES_DIR / name, files_stage / name)
        build_dataset_metadata(owner, files_stage / "dataset-metadata.json")

        kernel_stage = build_dir / "kernel"
        kernel_stage.mkdir()
        build_kernel_notebook(kernel_stage / "img2text_worker.ipynb")
        build_kernel_metadata(owner, args.accelerator, kernel_stage / "kernel-metadata.json")

        if not args.skip_dataset:
            push_dataset(api, owner, files_stage)
        push_kernel(api, owner, kernel_stage, args)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
