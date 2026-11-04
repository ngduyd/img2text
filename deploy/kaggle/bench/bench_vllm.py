"""Bench TÁCH RỜI: PaddleOCR-VL native (paddle) vs vLLM server backend — trên T4 của Kaggle.

Không đụng kernel sản xuất. Câu hỏi duy nhất: `vl_rec_backend="vllm-server"` có nhanh hơn
thật so với `predict()` native của repo không.

Kiến trúc bắt buộc (đúng docs): paddle stack và vLLM nằm ở 2 venv RIÊNG; client PaddleOCRVL
chỉ gọi vLLM qua HTTP. Cài paddle vào python hệ thống của Kaggle sẽ phá torch có sẵn
(`undefined symbol: ncclCommWindowDeregister`) — bench v1 đã chết đúng lỗi này.

Ra: /kaggle/working/bench_vllm_result.json + dòng `[bench] {...}`
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

IMAGE_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/"
    "paddleocr_vl_demo.png"
)
IMAGE = "/tmp/bench_page.png"
REPEATS = int(os.environ.get("BENCH_REPEATS") or 3)
PARALLEL = int(os.environ.get("BENCH_PARALLEL") or 3)
PORT = int(os.environ.get("VLLM_PORT") or 8000)
VLLM_PIP = (os.environ.get("VLLM_PIP") or "vllm").split()
PADDLE_VENV = "/tmp/paddle-venv"
VLLM_VENV = "/tmp/vllm-venv"
CLIENT = "/tmp/bench_client.py"
OUT = "/kaggle/working/bench_vllm_result.json"

# Repo flags (img2text_batch.py:172-174) — đo đúng cấu hình đang chạy thật.
NATIVE_ARGS = dict(
    pipeline_version="v1.5",
    vl_rec_model_name="PaddleOCR-VL-1.5-0.9B",
    layout_detection_model_name="PP-DocLayoutV3",
    use_doc_orientation_classify=True,
    use_doc_unwarping=True,
)

CLIENT_SRC = '''"""Client đo giờ — chạy TRONG paddle venv, 1 pipeline / process (PaddleX không cho
khởi tạo lần 2: "PDX has already been initialized")."""
import argparse, json, time
from concurrent.futures import ThreadPoolExecutor

NATIVE_ARGS = %r

def regions_of(res):
    try:
        data = res.json.get("res", res.json)
        return len(data.get("parsing_res_list") or [])
    except Exception:
        return -1

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend", required=True)  # native | vllm | vllm_par
    p.add_argument("--url", default="")
    p.add_argument("--image", required=True)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--parallel", type=int, default=0)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    from paddleocr import PaddleOCRVL
    kw = dict(NATIVE_ARGS)
    if a.backend.startswith("vllm"):
        kw["vl_rec_backend"] = "vllm-server"
        kw["vl_rec_server_url"] = a.url
    t = time.perf_counter()
    pipeline = PaddleOCRVL(**kw)
    out = {"backend": a.backend, "load_s": round(time.perf_counter() - t, 1)}

    def one(_=0):
        t0 = time.perf_counter()
        res = list(pipeline.predict(a.image))[0]
        return time.perf_counter() - t0, regions_of(res)

    dt, n = one()                      # warmup, không tính
    print(f"[bench] {a.backend} warmup {dt:.2f}s regions={n}", flush=True)
    seq = []
    for i in range(a.repeats):
        dt, n = one()
        seq.append(round(dt, 2))
        print(f"[bench] {a.backend} call {i}: {dt:.2f}s regions={n}", flush=True)
    out["seq_s"] = seq
    if a.parallel:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=a.parallel) as pool:
            list(pool.map(one, range(a.parallel)))
        out["parallel_s"] = round(time.perf_counter() - t0, 2)
        out["parallel_n"] = a.parallel
        print(f"[bench] {a.backend} x{a.parallel} song song: {out['parallel_s']}s", flush=True)
    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=2)
    print("[bench] client", json.dumps(out, ensure_ascii=False), flush=True)

main()
''' % (NATIVE_ARGS,)


def log(msg: str) -> None:
    print(f"[bench] {msg}", flush=True)


def run(cmd: list[str], **kw) -> int:
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, check=False, **kw).returncode


def uv(*args: str) -> int:
    return run(["uv", "pip", "install", "-p", *args])


def venv(path: str) -> str:
    if not os.path.exists(os.path.join(path, "bin", "python")):
        run(["uv", "venv", path, "--python", "3.12"])
    return os.path.join(path, "bin", "python")


def bench(backend: str, py: str, out: str, url: str = "", parallel: int = 0) -> bool:
    cmd = [py, CLIENT, "--backend", backend, "--image", IMAGE,
           "--repeats", str(REPEATS), "--out", out]
    if url:
        cmd += ["--url", url]
    if parallel:
        cmd += ["--parallel", str(parallel)]
    return run(cmd) == 0 and os.path.exists(out)


def merge(result: dict, path: str, prefix: str = "") -> None:
    try:
        data = json.load(open(path))
    except Exception as exc:
        log(f"đọc {path} lỗi: {exc}")
        return
    for k, v in data.items():
        result[f"{prefix}{k}"] = v


def start_vllm(py_venv: str) -> subprocess.Popen | None:
    if uv(py_venv, *VLLM_PIP) != 0:
        log("cài vLLM thất bại")
        return None
    bin_dir = os.path.dirname(py_venv)
    cmd = [
        os.path.join(bin_dir, "vllm"), "serve", "PaddlePaddle/PaddleOCR-VL",
        "--trust-remote-code",
        # client gửi `vl_rec_model_name` làm model id → phải expose đúng alias,
        # nếu không: 404 "model PaddleOCR-VL-1.5-0.9B does not exist"
        "--served-model-name", "PaddleOCR-VL-0.9B", "PaddleOCR-VL-1.5-0.9B",
        "--dtype", "float16",              # T4 = sm75, không có bf16
        "--max-num-batched-tokens", "8192",
        "--no-enable-prefix-caching",      # docs: OCR không cần prefix cache
        "--mm-processor-cache-gb", "0",
        # client (paddlex) gửi min/max_pixels per-request → vLLM chặn 400
        # "Per-request mm_processor_kwargs are disabled by default"
        "--trust-request-mm-kwargs",
        "--gpu-memory-utilization", "0.85",
        "--port", str(PORT),
    ]
    log("$ " + " ".join(cmd))
    env = dict(os.environ, VLLM_ATTENTION_BACKEND="XFORMERS")
    return subprocess.Popen(
        cmd, env=env, stdout=open("/tmp/vllm.log", "w"), stderr=subprocess.STDOUT
    )


def wait_vllm(proc: subprocess.Popen, timeout_s: float = 900) -> bool:
    url = f"http://127.0.0.1:{PORT}/v1/models"
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        if proc.poll() is not None:
            log(f"vllm chết (exit {proc.returncode}) — xem /tmp/vllm.log")
            return False
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    log(f"vllm sẵn sàng sau {time.perf_counter() - t0:.0f}s")
                    return True
        except Exception:
            pass
        time.sleep(5)
    log(f"vllm không lên sau {timeout_s:.0f}s")
    return False


def dump(result: dict) -> None:
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    urllib.request.urlretrieve(IMAGE_URL, IMAGE)
    open(CLIENT, "w", encoding="utf-8").write(CLIENT_SRC)
    result: dict = {"gpu": subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True, check=False).stdout.strip(),
        "repeats": REPEATS, "parallel": PARALLEL}
    log(f"GPU: {result['gpu']}")

    run([sys.executable, "-m", "pip", "install", "-q", "uv"])
    py = venv(PADDLE_VENV)
    uv(py, "paddlepaddle-gpu==3.2.1", "--extra-index-url",
       "https://www.paddlepaddle.org.cn/packages/stable/cu126/")
    uv(py, "paddleocr[doc-parser]>=3.6.0", "safetensors")

    if bench("native", py, "/tmp/native.json"):
        merge(result, "/tmp/native.json")
    dump(result)

    vllm_py = venv(VLLM_VENV)
    proc = start_vllm(vllm_py)
    if proc is not None:
        try:
            if wait_vllm(proc):
                url = f"http://127.0.0.1:{PORT}/v1"
                if bench("vllm", py, "/tmp/vllm.json", url=url):
                    merge(result, "/tmp/vllm.json")
                if bench("vllm_par", py, "/tmp/vllm_par.json", url=url,
                         parallel=PARALLEL):
                    merge(result, "/tmp/vllm_par.json", prefix="par_")
        except Exception as exc:
            log(f"stage vllm LỖI: {type(exc).__name__}: {exc}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()

    n, v = result.get("seq_s") or [], result.get("par_seq_s") or []
    if n:
        log(f"native  trung bình {sum(n) / len(n):.2f}s/ảnh")
    if v:
        result["speedup"] = round((sum(n) / len(n)) / (sum(v) / len(v)), 1) if n else None
        log(f"vllm    trung bình {sum(v) / len(v):.2f}s/ảnh → SPEEDUP {result.get('speedup')}x")
    if result.get("parallel_s"):
        log(f"vllm x{PARALLEL} song song: {result['parallel_s']}s "
            f"({result['parallel_s'] / PARALLEL:.2f}s/ảnh hiệu dụng)")
    dump(result)
    log(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
