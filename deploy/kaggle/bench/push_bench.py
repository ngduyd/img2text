"""Push kernel bench (PaddleOCR-VL native vs vLLM backend) lên Kaggle rồi chờ kết quả.

Chạy TRONG container server (nơi có package kaggle + creds KAGGLE_*):
    docker cp deploy/kaggle/bench deploy-server-1:/tmp/bench
    docker exec deploy-server-1 python /tmp/bench/push_bench.py /tmp/bench

Tách hẳn khỏi deploy/kaggle/push.py (push.py lo kernel sản xuất + dataset).
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

SLUG = os.environ.get("KERNEL_SLUG") or "img2text-bench-vllm"
META = os.environ.get("KERNEL_META") or "kernel-bench-metadata.json"
EXTRA = [x for x in (os.environ.get("KERNEL_EXTRA") or "").split(",") if x]
TERMINAL = {"complete", "error", "cancelacknowledged", "cancelrequested"}


def load_env() -> tuple[str, str]:
    user = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    token = os.environ.get("KAGGLE_API_TOKEN", "").strip()
    if not user or not (key or token):
        sys.exit("error: cần KAGGLE_USERNAME + KAGGLE_API_TOKEN (hoặc KAGGLE_KEY)")
    return user, key


def stage(owner: str, src: Path) -> Path:
    """metadata (id OWNER/…) + code → /tmp/bench-stage."""
    dest = Path("/tmp/bench-stage")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    meta = json.loads((src / META).read_text(encoding="utf-8"))
    meta["id"] = f"{owner}/{SLUG}"
    (dest / "kernel-metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    shutil.copyfile(src / meta["code_file"], dest / meta["code_file"])
    for name in EXTRA:  # file phụ (vd module sản xuất cần import trong smoke)
        shutil.copyfile(src / name, dest / name)
    return dest


def status_of(api, ref: str) -> tuple[str, str]:
    try:
        resp = api.kernels_status(ref)
    except Exception as exc:  # kernel mới: status có thể 404 ở lần đầu
        return f"unknown ({type(exc).__name__})", ""
    raw = getattr(resp, "status", None) or resp.get("status") or ""
    name = getattr(raw, "name", None) or str(raw)
    return name.lower().replace("kernelworkerstatus.", ""), (
        getattr(resp, "failureMessage", "") or ""
    )


def main() -> int:
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__)
    src = arg.resolve() if arg.is_dir() else arg.resolve().parent
    owner, _key = load_env()
    from kaggle import api

    api.authenticate()
    ref = f"{owner}/{SLUG}"
    meta = json.loads((src / META).read_text(encoding="utf-8"))
    meta["id"] = ref
    try:
        api.kernels_push(
            str(stage(owner, src)),
            no_run=False,
            timeout=21600,
            accelerator=meta["accelerator"],
        )
    except TypeError:
        print("note: kaggle package thiếu kwargs (no_run/timeout/accelerator)")
        api.kernels_push(str(stage(owner, src)))

    print(f"pushed {ref}; chờ tối đa 90 phút")
    deadline = time.time() + 90 * 60
    last = ""
    while time.time() < deadline:
        status, msg = status_of(api, ref)
        if status != last:
            print(f"  status: {status}" + (f" — {msg}" if msg else ""))
            last = status
        if status in TERMINAL:
            break
        time.sleep(45)

    out = Path("/tmp/bench-output")
    os.makedirs(out, exist_ok=True)
    try:
        api.kernels_output(ref, str(out))
        print(f"output → {out}")
        for f in sorted(out.rglob("*")):
            if f.is_file():
                print(f"  {f.name} ({f.stat().st_size}B)")
        res = out / "bench_stages_result.json"
        res2 = out / "bench_vllm_result.json"
        for r in (res, res2):
            if r.exists():
                print("RESULT:", r.read_text(encoding="utf-8"))
        log = next(iter(sorted(out.glob("*.log"))), out / "bench_vllm.log")
        if log.exists():
            print("--- log đuôi ---")
            print("\n".join(log.read_text(encoding="utf-8").splitlines()[-40:]))
    except Exception as exc:
        print(f"kernels_output lỗi: {type(exc).__name__}: {exc}")
    return 0 if last == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
