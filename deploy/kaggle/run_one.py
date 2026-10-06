#!/usr/bin/env python3
"""Kaggle batch mode (Plan K3): push input → run kernel → pull output.

No backend public / no secrets — client drives everything via
KaggleApi. Production K2 polling-backend mode (push.py) is untouched.

ponytail ceilings: 1 input file per run (directory → error), single shared
"img2text-input" dataset slug (parallel runs overwrite each other), output
fetched into a fresh ./out/<timestamp-micros>/ subdir.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import kcompat
import push  # noqa: F401  # sibling module: load_env + _sub_owner patterns

DEPLOY_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEPLOY_DIR.parent.parent
WORKER_DIR = REPO_ROOT / "worker"
KERNEL_NB = DEPLOY_DIR / "kernel" / "img2text_batch.ipynb"
KERNEL_META_TPL = DEPLOY_DIR / "kernel" / "kernel-metadata.json"
WORKER_META_TPL = DEPLOY_DIR / "files" / "dataset-metadata.json"

INPUT_SLUG = "img2text-input"
WORKER_SLUG = "img2text-worker-files"
DEFAULT_KERNEL_SLUG = "img2text-batch"
DEFAULT_ACCELERATOR = "NvidiaTeslaT4"
DEFAULT_TIMEOUT = 3600
DEFAULT_POLL = 20
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

SLEEP = time.sleep  # module-level: tests inject a fake sleeper

def load_env():
    return push.load_env()

def _write_meta(meta, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def stage_input(src: Path, owner: str, stage: Path):
    """Temp stage: input file + dataset-metadata.json (title img2text-input)."""
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, stage / src.name)
    _write_meta(
        {"id": f"{owner}/{INPUT_SLUG}", "title": INPUT_SLUG, "licenses": ["CC0-1.0"]},
        stage / "dataset-metadata.json",
    )

def stage_worker(owner: str, stage: Path):
    """Worker files at dataset ROOT (K2 push.py layout) AND under worker/
    (K3 batch sys.path mount) — both layouts in one dataset."""
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "worker").mkdir(exist_ok=True)
    for name in ("pipeline.py", "verdict.py"):
        shutil.copyfile(WORKER_DIR / name, stage / name)
        shutil.copyfile(WORKER_DIR / name, stage / "worker" / name)
    meta = json.loads(WORKER_META_TPL.read_text(encoding="utf-8"))
    meta["id"] = f"{owner}/{WORKER_SLUG}"
    _write_meta(meta, stage / "dataset-metadata.json")

def ensure_dataset(api, owner: str, slug: str, stage: Path, refresh: bool = False):
    """Dataset absent → kcompat create (kaggle 2.2.4 dataset_create_new).

    Exists check uses a REAL list method (kcompat.api_dataset_exists,
    hasattr-verified) — the old code try/except-ed the CREATE call and
    swallowed any exception (incl. AttributeError from the renamed API)
    as "dataset exists".

    refresh=True (input dataset): exists → kcompat DELETE + recreate with
    the staged folder (both kcompat paths upload files; a bare version bump
    would serve the previous file — stale).
    refresh=False (worker-files): exists → keep as-is (shared with K2;
    notebook falls back to the root layout if worker/ is missing).
    """
    ref = f"{owner}/{slug}"
    try:
        exists = kcompat.api_dataset_exists(api, ref)
    except Exception as exc:
        sys.exit(f"error: dataset {ref}: exists check failed ({exc})")
    if exists and not refresh:
        print(f"dataset exists; keeping: {ref}")
        return
    if exists:
        print(f"dataset exists; delete+recreate: {ref}")
        try:
            deleted = kcompat.api_delete_dataset(api, ref)
        except Exception as exc:
            sys.exit(f"error: dataset {ref}: delete failed ({exc})")
        if not deleted:
            sys.exit(
                f"error: dataset {ref}: delete unavailable "
                "(kaggle package has no delete API) — cannot replace"
            )
    try:
        kcompat.api_create_dataset(api, str(stage))
        print(f"dataset created: {ref}")
    except Exception as exc:
        sys.exit(f"error: dataset {ref}: create failed ({exc})")

def build_kernel_stage(owner: str, accelerator: str, kernel_ref: str, stage: Path):
    """Copy batch notebook + write kernel-metadata.json (OWNER substituted)."""
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_NB, stage / KERNEL_NB.name)
    meta = push._sub_owner(json.loads(KERNEL_META_TPL.read_text(encoding="utf-8")), owner)
    meta["id"] = kernel_ref
    meta["title"] = kernel_ref.split("/")[-1]
    meta["code_file"] = KERNEL_NB.name
    meta["dataset_sources"] = [f"{owner}/{WORKER_SLUG}", f"{owner}/{INPUT_SLUG}"]
    meta["machine_shape"] = accelerator
    meta["accelerator"] = accelerator
    _write_meta(meta, stage / "kernel-metadata.json")
    return stage

def _status_of(resp):
    return resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None)

def wait_complete(api, ref: str, poll: int, timeout: int):
    """Poll kernels_status every `poll` s. complete → return; failed → exit 1;
    timeout → exit 2. Elapsed counted in poll units (deterministic, testable)."""
    elapsed = 0
    while True:
        status = _status_of(api.kernels_status(ref))
        print(f"kernel {ref}: status={status} (elapsed {elapsed}s / {timeout}s)")
        if status == "complete":
            return
        if status == "failed":
            print(f"error: kernel {ref} failed — check kaggle kernels log {ref}", file=sys.stderr)
            sys.exit(1)
        if elapsed >= timeout:
            print(
                f"error: timeout {timeout}s waiting for {ref}\n"
                "hint: giới hạn 1 input dataset slug dùng chung (img2text-input) — "
                "song song sẽ đè nhau; tăng --timeout hoặc chờ quota GPU.",
                file=sys.stderr,
            )
            sys.exit(2)
        SLEEP(poll)
        elapsed += poll

def pull_output(api, ref: str, out_root: str):
    """Fresh ./out/<timestamp-micros>/ subdir per run — old output never
    mixes in, even for back-to-back runs within the same second."""
    out_dir = Path(out_root) / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_dir.mkdir(parents=True, exist_ok=True)
    api.kernels_output(ref, path=str(out_dir), quiet=False)
    files = sorted(p.name for p in out_dir.rglob("*") if p.is_file())
    print(f"output: {out_dir}")
    for name in files:
        print(f"  - {name}")
    return out_dir

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Kaggle batch mode: push 1 input file → run kernel → pull output"
    )
    parser.add_argument("input", help="input file (jpg/jpeg/png/webp/pdf)")
    parser.add_argument("--accelerator", default=DEFAULT_ACCELERATOR, help="GPU accelerator id")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="wait timeout seconds")
    parser.add_argument("--poll", type=int, default=DEFAULT_POLL, help="poll interval seconds")
    parser.add_argument("--out", default="./out", help="output root dir (fresh subdir per run)")
    parser.add_argument("--kernel-ref", default=None, help="owner/slug (default OWNER/img2text-batch)")
    args = parser.parse_args(argv)
    args.poll = max(1, args.poll)  # ponytail: poll<=0 would busy-loop the status poll

    owner, _key = load_env()

    src = Path(args.input)
    if src.is_dir():
        # ponytail: 1 file/lần — directory batching khi thật sự cần
        sys.exit(f"error: directory chưa hỗ trợ, gửi 1 file: {src}")
    if not src.is_file():
        sys.exit(f"error: file not found: {src}")
    if src.suffix.lower() not in EXTS:
        sys.exit(f"error: unsupported extension {src.suffix} (jpg/jpeg/png/webp/pdf)")
    kernel_ref = args.kernel_ref or f"{owner}/{DEFAULT_KERNEL_SLUG}"

    try:
        from kaggle import KaggleApi
    except ImportError:
        sys.exit("error: kaggle package missing — pip install kaggle")
    api = KaggleApi()
    api.authenticate()

    build = Path(tempfile.mkdtemp(prefix="kaggle-img2text-batch-"))
    try:
        worker_stage = build / "worker-files"
        stage_worker(owner, worker_stage)
        ensure_dataset(api, owner, WORKER_SLUG, worker_stage)

        input_stage = build / "input"
        stage_input(src, owner, input_stage)
        ensure_dataset(api, owner, INPUT_SLUG, input_stage, refresh=True)

        kernel_stage = build / "kernel"
        build_kernel_stage(owner, args.accelerator, kernel_ref, kernel_stage)
        print(f"kernel: push {kernel_ref}")
        api.kernels_push(str(kernel_stage))

        wait_complete(api, kernel_ref, args.poll, args.timeout)
        pull_output(api, kernel_ref, args.out)
    finally:
        shutil.rmtree(build, ignore_errors=True)

if __name__ == "__main__":
    main()
