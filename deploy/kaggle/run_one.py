#!/usr/bin/env python3
"""Kaggle batch mode (Plan K4): push input → run script kernel → pull output.

Standalone single-file kernel (kernel/img2text_batch.py, kernel_type
"script") — no worker-files dataset. No backend public / no secrets —
client drives everything via KaggleApi. Production K2 polling-backend mode
(push.py) is untouched.

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
KERNEL_SCRIPT = DEPLOY_DIR / "kernel" / "img2text_batch.py"
KERNEL_META_TPL = DEPLOY_DIR / "kernel" / "kernel-batch-metadata.json"

# Slug RIÊNG cho chạy tay: orchestrator server cũng stage cùng dataset
# "img2text-input" (manifest.json) → hai writer đè nhau, verify fail và job
# của người này bị kernel của người kia xử lý.
INPUT_SLUG = "img2text-input-manual"
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

def staged_name(name: str, job_id: int) -> str:
    """Tên file trong dataset PHẢI có prefix `{job_id}__` — kernel bỏ qua file
    không có prefix số (spec 2026-10-09: server stage theo cùng contract)."""
    return f"{job_id}__{name}"

def stage_input(src: Path, owner: str, stage: Path, job_id: int,
                opts: dict | None = None):
    """Temp stage: input file (prefix job_id) + dataset-metadata.json (+opts)."""
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, stage / staged_name(src.name, job_id))
    if opts:
        (stage / "batch_opts.json").write_text(
            json.dumps(opts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    _write_meta(
        {
            "id": f"{owner}/{INPUT_SLUG}",
            "title": INPUT_SLUG,
            "licenses": [{"name": "CC0-1.0"}],
        },
        stage / "dataset-metadata.json",
    )

def ensure_dataset(api, owner: str, slug: str, stage: Path, refresh: bool = False):
    """Dataset absent → kcompat create (kaggle 2.2.4 dataset_create_new).

    Exists check uses a REAL list method (kcompat.api_dataset_exists,
    hasattr-verified) — the old code try/except-ed the CREATE call and
    swallowed any exception (incl. AttributeError from the renamed API)
    as "dataset exists".

    refresh=True (input dataset): exists → kcompat DELETE + recreate with
    the staged folder (both kcompat paths upload files; a bare version bump
    would serve the previous file — stale).
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

VERIFY_TIMEOUT = 120.0
VERIFY_INTERVAL = 3.0

def verify_dataset(api, owner: str, slug: str, expected: str,
                   timeout: float = VERIFY_TIMEOUT, interval: float = VERIFY_INTERVAL):
    """Dataset vừa tạo PHẢI chứa đúng file staged.

    Bug thật: `img2text-input` còn `manifest.json` cũ (2026-10-17) → kernel đi
    URL-mode, tải job cũ 403 → "không có input" → chạy rỗng, đốt 10 phút GPU.
    Fail sớm ở client rẻ hơn nhiều. `dataset_list_files` sau delete+recreate
    trả version CŨ trong vài giây (eventual consistency) → poll, đừng fail ngay.
    """
    ref = f"{owner}/{slug}"
    deadline = time.monotonic() + timeout
    while True:
        try:
            files = kcompat.api_dataset_files(api, ref)
        except Exception:   # 403/list lỗi ngay sau delete+create = chưa index
            files = set()
        if expected in files:
            return
        if time.monotonic() >= deadline:
            sys.exit(
                f"error: dataset {ref} thiếu {expected} (có: {sorted(files)}) — "
                "dataset chưa refresh; xoá dataset rồi chạy lại"
            )
        SLEEP(interval)

def build_kernel_stage(owner: str, accelerator: str, kernel_ref: str, stage: Path):
    """Copy standalone script + write kernel-metadata.json (OWNER substituted).

    Template = kernel-batch-metadata.json (kernel_type "script",
    dataset_sources: input dataset ONLY — worker files live IN the script).
    """
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_SCRIPT, stage / KERNEL_SCRIPT.name)
    meta = push._sub_owner(json.loads(KERNEL_META_TPL.read_text(encoding="utf-8")), owner)
    # dataset_sources: input RIÊNG + giữ các dataset khác (wheels) từ template
    sources = [
        ref for ref in meta.get("dataset_sources") or []
        if not str(ref).endswith("/img2text-input")
    ]
    meta["dataset_sources"] = [f"{owner}/{INPUT_SLUG}"] + sources
    meta["id"] = kernel_ref
    meta["title"] = kernel_ref.split("/")[-1]
    meta["code_file"] = KERNEL_SCRIPT.name
    meta["machine_shape"] = accelerator
    meta["accelerator"] = accelerator
    _write_meta(meta, stage / "kernel-metadata.json")
    return stage

_norm_status = push._norm_status  # shared: kaggle 2.2.4 enum-repr → 'complete'

def wait_complete(api, ref: str, poll: int, timeout: int):
    """Poll kernels_status every `poll` s. complete → return; failed/error → exit 1;
    timeout → exit 2. Elapsed counted in poll units (deterministic, testable).
    Status normalized: live kaggle returns KernelWorkerStatus.COMPLETE reprs."""
    elapsed = 0
    while True:
        status = _norm_status(api.kernels_status(ref))
        print(f"kernel {ref}: status={status} (elapsed {elapsed}s / {timeout}s)")
        if status == "complete":
            return
        if status in ("failed", "error"):
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

def claim_job(api_url: str, runner_key: str, want_id: int | None):
    """GET /api/jobs/next (worker protocol) → (job dict, file bytes).

    Dùng runner key nên KHÔNG cần cookie đăng nhập: đúng đường worker thật,
    chỉ khác là OCR chạy trên Kaggle batch thay vì kernel session.
    """
    import httpx

    with httpx.Client(timeout=120) as c:
        r = c.get(f"{api_url}/api/jobs/next", headers={"Authorization": f"Bearer {runner_key}"})
        if r.status_code == 204:
            sys.exit("error: queue rỗng — không có job nào để claim")
        r.raise_for_status()
        job = r.json()
        if want_id is not None and job["job_id"] != want_id:
            sys.exit(
                f"error: claim được job {job['job_id']} (hàng đợi lấy job cũ nhất), "
                f"không phải {want_id} — job {job['job_id']} vẫn đang giữ lease; "
                f"chạy lại với --job {job['job_id']}"
            )
        data = c.get(job["file_url"]).content
        return job, data

def post_result(api_url: str, job: dict, doc: dict) -> None:
    """result.json (K4 document shape) → ResultBody (adapt_batch_document) →
    POST /api/jobs/{id}/result — cùng payload server tự ingest ở chế độ batch."""
    import httpx

    try:
        from app.services.kaggle_orchestrator import adapt_batch_document
    except ImportError:  # chạy ngoài container server
        sys.exit(
            "error: cần chạy trong container server để adapt result "
            "(docker exec img2text-dev-server-1 python deploy/kaggle/run_one.py ...)"
        )
    body = adapt_batch_document(doc)
    with httpx.Client(timeout=120) as c:
        r = c.post(
            f"{api_url}/api/jobs/{job['job_id']}/result",
            json=body,
            headers={"Authorization": f"Bearer {job['worker_token']}"},
        )
        if r.status_code != 200:
            sys.exit(f"error: POST result {r.status_code}: {r.text[:200]}")
        print(f"result: job {job['job_id']} ingested ({len(body['pages'][0]['regions'])} regions)")

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Kaggle batch mode: push 1 input file → run kernel → pull output"
    )
    parser.add_argument("input", nargs="?", help="input file (jpg/jpeg/png/webp/pdf)")
    parser.add_argument("--job", type=int, default=None,
                        help="claim job N từ API (worker protocol) rồi chạy batch cho job đó")
    parser.add_argument("--job-id", type=int, default=1,
                        help="prefix job_id cho file local (kernel bỏ qua file không có prefix); "
                             "cũng là tên output `<id>_result.json`")
    parser.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE",
                        help="cờ pipeline cho kernel (vd --opt unwarp=false); ghi batch_opts.json")
    parser.add_argument("--api", default=os.environ.get("IMG2TEXT_API", "http://localhost:8000"),
                        help="API base của server (mặc định http://localhost:8000 trong container)")
    parser.add_argument("--runner-key", default=os.environ.get("RUNNER_KEY", ""),
                        help="runner key để claim job (mặc định env RUNNER_KEY)")
    parser.add_argument("--accelerator", default=DEFAULT_ACCELERATOR, help="GPU accelerator id")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="wait timeout seconds")
    parser.add_argument("--poll", type=int, default=DEFAULT_POLL, help="poll interval seconds")
    parser.add_argument("--out", default="./out", help="output root dir (fresh subdir per run)")
    parser.add_argument("--kernel-ref", default=None, help="owner/slug (default OWNER/img2text-batch)")
    args = parser.parse_args(argv)
    args.poll = max(1, args.poll)  # ponytail: poll<=0 would busy-loop the status poll

    owner, _key = load_env()

    job = None
    if args.job is not None:
        if not args.runner_key:
            sys.exit("error: --runner-key (hoặc env RUNNER_KEY) bắt buộc khi claim job")
        job, data = claim_job(args.api, args.runner_key, args.job)
        ext = "pdf" if job["file_type"] == "pdf" else "png"
        tmp_src = Path(tempfile.mkdtemp(prefix="img2text-claim-")) / f"job{job['job_id']}.{ext}"
        tmp_src.write_bytes(data)
        src, job_id = tmp_src, job["job_id"]
        print(f"claimed job {job_id} ({job['file_type']}, {len(data)} bytes)")
    else:
        if not args.input:
            sys.exit("error: cần input file hoặc --job N")
        src = Path(args.input)
        job_id = args.job_id
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
        input_stage = build / "input"
        opts = {}
        for item in args.opt:
            key, _, raw = item.partition("=")
            if not key or not raw:
                sys.exit(f"error: --opt cần KEY=VALUE, nhận {item!r}")
            opts[key] = raw.lower() not in ("0", "false", "no")
        stage_input(src, owner, input_stage, job_id, opts or None)
        ensure_dataset(api, owner, INPUT_SLUG, input_stage, refresh=True)
        verify_dataset(api, owner, INPUT_SLUG, staged_name(src.name, job_id))

        kernel_stage = build / "kernel"
        build_kernel_stage(owner, args.accelerator, kernel_ref, kernel_stage)
        print(f"kernel: push {kernel_ref}")
        api.kernels_push(str(kernel_stage))

        wait_complete(api, kernel_ref, args.poll, args.timeout)
        out_dir = pull_output(api, kernel_ref, args.out)
        if job is not None:
            result_file = out_dir / f"{job_id}_result.json"
            if not result_file.is_file():
                sys.exit(f"error: kernel không tạo {result_file.name} trong {out_dir}")
            post_result(args.api, job, json.loads(result_file.read_text(encoding="utf-8")))
    finally:
        shutil.rmtree(build, ignore_errors=True)

if __name__ == "__main__":
    main()
