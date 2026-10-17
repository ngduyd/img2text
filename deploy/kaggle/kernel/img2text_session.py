"""Kaggle session loop worker kernel (spec 2026-10-16 T7) — ONE session, N jobs.

kernel_type "script": orchestrator _spawn_session stage + push CÙNG
img2text_batch.py (shared module — venv bootstrap / per-page resume cache /
SIGALRM watchdog / pipeline flags: import lại, KHÔNG copy-paste).
__SESSION_KEY__ / __BASE_URL__ placeholder được substitute lúc staged push
(script chứa key + base URL; kernel-metadata KHÔNG). Resolve env-first.

Flow: bootstrap 1×/session (kb.bootstrap_venv) → re-exec dưới
/tmp/paddle-venv/bin/python → loop:
  1. GET {BASE_URL}/api/jobs/next (Bearer session key) — 200 JSON claim;
     {"empty": true} hoặc server_flags.quota_low → exit 0 (AC5).
  2. download input (presign GET, verify sha256) → rasterize → precheck →
     preprocess; per-page resume qua ocr_raw json cache (kb, giữ nguyên).
  3. OCR: model load 1×/session (singleton) + SIGALRM watchdog per trang
     (kb._predict_pages_one_by_one); giữa các trang poll GET
     /api/jobs/{id}/status → cancelled → bỏ job, sang job sau (AC7).
  4. adapt document → §4 payload → PUT result.json + crops (presigned PUT
     từ claim) → POST /result (Bearer) → lặp; per-job error → POST /fail →
     tiếp (AC10). Heartbeat /api/worker/heartbeat mỗi 5 phút.
  5. session budget < 30min còn lại → exit 0 trước ~9h Kaggle limit.

Exit codes: 0 = graceful, 1 = unrecoverable, 90 = session-level bootstrap
fail (venv/import — server respawn, AC10).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

import img2text_batch as kb  # staged alongside; stdlib-only import (cheap)

SESSION_KEY_PLACEHOLDER = "__SESSION_KEY__"
# orchestrator _sub_owner-style substitute lúc staged push; test tự set.
BASE_URL_PLACEHOLDER = "__BASE_URL__"

def _baked_env(name: str, placeholder: str) -> str:
    """Resolve env-first: os.environ (Secrets/manual override) THẮNG; chưa có
    → giá trị placeholder (đã substitute lúc staged push = bake). Placeholder
    còn nguyên (chưa push, literal __NAME__) + không env → ''. Ghi lại vào
    os.environ để re-exec (os.execve) giữ được."""
    value = os.environ.get(name) or placeholder
    if value == f"__{name}__":
        return ""
    os.environ[name] = value
    return value

SESSION_KEY = _baked_env("SESSION_KEY", SESSION_KEY_PLACEHOLDER)
BASE_URL = _baked_env("BASE_URL", BASE_URL_PLACEHOLDER)
# Session budget: exit 0 trước khi chạm ~9h Kaggle limit (margin 30 phút).
SESSION_MAX_AGE_S = float(os.environ.get("SESSION_MAX_AGE_S") or 30600)
BUDGET_EXIT_MARGIN_S = 1800.0
HEARTBEAT_INTERVAL_S = 300.0
# Claim 429 (rate-limiter transient): retry CÓ CAP rồi mới EXIT_FATAL — không
# treo kernel vĩnh viễn khi limiter nghẽn kéo dài.
CLAIM_MAX_RETRIES = int(os.environ.get("SESSION_CLAIM_MAX_RETRIES") or 5)
CLAIM_BACKOFF_BASE_S = 2.0
CLAIM_BACKOFF_MAX_S = 60.0

EXIT_GRACEFUL = 0
EXIT_FATAL = 1
EXIT_SESSION_LEVEL = 90

# mirror orchestrator BATCH_MODEL_VERSION / schemas.IMAGE_MARKER — parity test
VL_MODEL_VERSION = "PaddleOCR-VL-1.5-0.9B"
IMAGE_MARKER = "**[Hình ảnh chưa trích xuất: vùng {region_id}]**"
_MD_PREFIX = {"doc_title": "# ", "paragraph_title": "## "}


# ===========================================================================
# HTTP helpers (stdlib urllib — server JSON surface, Bearer session key)
# ===========================================================================

def _http_json(method: str, url: str, key: str, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, method=method, data=data,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return json.loads(body) if body else {}

def _put_bytes(url: str, data: bytes, timeout=300) -> None:
    req = urllib.request.Request(url, method="PUT", data=data)
    with urllib.request.urlopen(req, timeout=timeout):
        pass

def _heartbeat(base: str, key: str) -> None:
    """Best-effort telemetry (server poll marker đã chính); lỗi không kill
    session."""
    try:
        _http_json("POST", f"{base}/api/worker/heartbeat", key, {
            "worker_id": "kaggle-session", "kind": "kaggle-session",
        })
    except Exception as exc:
        print(f"[session] heartbeat lỗi: {exc}", flush=True)

def _status(base: str, key: str, job_id: int) -> dict:
    return _http_json("GET", f"{base}/api/jobs/{job_id}/status", key)

def _cancel_check(base: str, key: str, job_id: int) -> bool:
    """True = chưa cancel (tiếp tục OCR). 429/timeout lúc poll status là
    transient (limiter nghẽn) → coi như chưa cancel, KHÔNG raise — tránh fail
    SAI job. Lỗi HTTP khác (401/403/...) vẫn raise như cũ."""
    try:
        return _status(base, key, job_id).get("status") != "cancelled"
    except urllib.error.HTTPError as exc:
        if exc.code != 429:
            raise
        err = exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        err = exc
    print(f"[session] cancel_check job {job_id} transient ({err}) "
          "— coi như chưa cancel", flush=True)
    return True


# ===========================================================================
# OCR: model singleton 1×/session (AC2) — kb giữ pipeline flags proven
# ===========================================================================

_pipeline = None

def _make_pipeline():
    from paddleocr import PaddleOCRVL

    return PaddleOCRVL(
        pipeline_version=kb.PIPELINE_VERSION,
        vl_rec_model_name=kb.VL_MODEL,
        layout_detection_model_name=kb.LAYOUT_MODEL,
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
    )

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = _make_pipeline()
        print("[session] nạp model xong (1×/session)", flush=True)
    return _pipeline

def process_job_session(job_id: int, input_path: str, preprocess_spec, cancel_check):
    """kb.process_job flow với OCR IN-PROCESS (model singleton — không re-exec
    subprocess per job); per-page resume = ocr_raw json cache; SIGALRM watchdog
    = kb._predict_pages_one_by_one.

    Returns (document, crops) hoặc None khi cancel_check() False giữa các trang
    (AC7 — giữ cache, không upload)."""
    from pathlib import Path

    import numpy as np
    from PIL import Image

    job_dir = os.path.join(kb.WORK_DIR, f"job_{job_id}")
    raw_dir = Path(job_dir, "pages_raw")
    pre_dir = Path(job_dir, "pages_pre")
    ocr_raw_dir = Path(job_dir, "ocr_raw")
    os.makedirs(pre_dir, exist_ok=True)
    os.makedirs(ocr_raw_dir, exist_ok=True)

    raw_paths = kb._apply_preprocess(
        kb.rasterize_to_pages(input_path, raw_dir), preprocess_spec
    )
    pre_info: dict[str, dict] = {}
    ready: list[str] = []
    for p in raw_paths:
        name = os.path.basename(p)
        arr = np.array(Image.open(p))
        pc = kb.precheck(arr)
        if pc.blurry and pc.too_small:
            h, w = arr.shape[:2]
            pre_info[name] = {"width": w, "height": h, "gated": True}
            print(f"{name}: precheck unreadable — bỏ qua OCR", flush=True)
            continue
        pre_info[name] = kb.preprocess(p, os.path.join(pre_dir, name))
        ready.append(os.path.join(pre_dir, name))

    def to_jsonable(o):
        return o.tolist() if hasattr(o, "tolist") else str(o)

    def save(p, data, t):
        (ocr_raw_dir / (Path(p).stem + ".json")).write_text(
            json.dumps(data, ensure_ascii=False, default=to_jsonable),
            encoding="utf-8",
        )
        err = ocr_raw_dir / (Path(p).stem + ".error.txt")
        if err.exists():
            err.unlink()
        print(f"{Path(p).name}: xong ({t:.0f}s)", flush=True)

    if ready:
        pages = [Path(p) for p in ready]
        todo = [p for p in pages
                if not (ocr_raw_dir / f"{p.stem}.json").exists()]
        if todo:
            ok = kb._predict_pages_one_by_one(
                get_pipeline(), todo, save, ocr_raw_dir,
                cancel_check=cancel_check,
            )
            if not ok:
                print(f"[session] job {job_id} cancelled giữa trang — bỏ job",
                      flush=True)
                return None

    raw_paths_p = [str(p) for p in raw_paths]
    pages_out, problems = kb.normalize(
        raw_paths_p, pre_info, ocr_raw_dir, pre_dir
    )
    try:
        crops = kb.extract_crops(input_path, pages_out)
    except Exception as exc:
        crops = {}
        print(f"[session] job {job_id} crop extract lỗi: {exc}", flush=True)
    document = {"source_pdf": input_path, "dpi": getattr(kb, "DPI", 200),
                "pages": pages_out, "problems": problems}
    return document, crops


# ===========================================================================
# adapt_document — mirror orchestrator.adapt_batch_document (kernel không
# import server được; parity test pin 2 phía bằng nhau trên cùng doc)
# ===========================================================================

def _band_tol(h1: float, h2: float) -> float:
    return max(10.0, 0.3 * max(h1, h2))

def _linearize_blocks(blocks: list[dict]) -> list[dict]:
    keyed = []
    for i, b in enumerate(blocks):
        bbox = b.get("bbox")
        if bbox and len(bbox) == 4:
            cy, h, x0 = (bbox[1] + bbox[3]) / 2, abs(bbox[3] - bbox[1]), bbox[0]
        else:
            cy, h, x0 = float("inf"), 0.0, 0
        keyed.append((cy, h, x0, i, b))
    keyed.sort(key=lambda t: (t[0], t[3]))
    out: list[tuple] = []
    band: list[tuple] = []
    for t in keyed:
        if (band and t[0] != float("inf")
                and t[0] - band[-1][0] <= _band_tol(t[1], band[-1][1])):
            band.append(t)
        else:
            out.extend(sorted(band, key=lambda z: z[2]))
            band = [t]
    out.extend(sorted(band, key=lambda z: z[2]))
    return [t[4] for t in out]

def _cells_md(cells: list[list[dict]]) -> str:
    if not cells:
        return ""
    h = next((i for i, r in enumerate(cells)
              if any(c.get("header") for c in r)), 0)

    def texts(row):
        return [str(c.get("text") or "") for c in row]

    def fmt(row):
        return "| " + " | ".join(t.replace("|", "\\|") for t in texts(row)) + " |"
    head = texts(cells[h])
    lines = [fmt(cells[h]), "| " + " | ".join(["---"] * len(head)) + " |"]
    lines += [fmt(r) for i, r in enumerate(cells) if i != h]
    return "\n".join(lines)

def adapt_document(doc: dict) -> dict:
    """notebook document shape → spec §4 ResultBody payload — mirror
    orchestrator.adapt_batch_document (parity test pin)."""
    md_pages: list[str] = []
    pages_out: list[dict] = []
    for i, pg in enumerate(doc.get("pages") or [], 1):
        regions: list[dict] = []
        md_parts: list[str] = []
        last_marker = None
        for b in _linearize_blocks(pg.get("blocks") or []):
            text = b.get("text") or ""
            is_image = b.get("type") == "image"
            if not is_image and not text.strip():
                continue
            rid = str(b.get("id") or f"p{i}_b{len(regions)}")
            region = {
                "id": rid,
                "bbox": b.get("bbox"),
                "text": text,
                "verdict": "image_unextractable" if is_image else "ok",
                "placeholder": is_image,
            }
            if b.get("html"):
                region["html"] = b["html"]
            if b.get("cells"):
                region["cells"] = b["cells"]
            regions.append(region)
            pos = None
            if is_image:
                piece = IMAGE_MARKER.format(region_id=rid)
                bbox = b.get("bbox")
                if bbox and len(bbox) == 4:
                    pos = ((bbox[1] + bbox[3]) / 2, abs(bbox[3] - bbox[1]))
            elif b.get("cells"):
                piece = _cells_md(b["cells"])
            else:
                piece = _MD_PREFIX.get(b.get("type"), "") + text
            if not piece:
                continue
            if (md_parts and last_marker is not None and pos is not None
                    and abs(pos[0] - last_marker[0])
                    <= _band_tol(pos[1], last_marker[1])):
                md_parts[-1] += " " + piece
            else:
                md_parts.append(piece)
            last_marker = pos
        page_md = "\n\n".join(md_parts)
        pages_out.append({
            "index": int(pg.get("page") or i),
            "width": int(pg.get("width") or 0),
            "height": int(pg.get("height") or 0),
            "page_flag": "ok",
            "markdown": page_md,
            "regions": regions,
        })
        md_pages.append(page_md)
    return {
        "model_version": VL_MODEL_VERSION,
        "gpu_seconds": 0.0,
        "warnings": [str(p) for p in doc.get("problems") or []],
        "markdown": "\n\n---\n\n".join(md_pages),
        "edited_markdown": None,
        "pages": pages_out,
    }


# ===========================================================================
# Loop (AC2/AC5/AC7/AC10)
# ===========================================================================

def run_job(base: str, key: str, claim: dict) -> str:
    """ONE claim → OCR → upload → done/fail. Returns 'done'|'failed'|'cancelled'."""
    job_id = claim["job_id"]
    t0 = time.time()
    try:
        from pathlib import Path

        dest = os.path.join(kb.WORK_DIR, "inputs",
                            f"job_{job_id}_{Path(claim['file_url'].split('?', 1)[0]).name}")
        kb.fetch_input(claim["file_url"], dest, claim.get("sha256"))
        out = process_job_session(
            job_id, dest, claim.get("preprocess"),
            cancel_check=lambda: _cancel_check(base, key, job_id),
        )
        if out is None:
            return "cancelled"
        doc, crops = out
        if not _cancel_check(base, key, job_id):
            return "cancelled"  # cancel cuối OCR → giữ partial, không upload
        payload = adapt_document(doc)
        payload["gpu_seconds"] = round(time.time() - t0, 2)
        _put_bytes(claim["result_upload_url"],
                   json.dumps(payload, ensure_ascii=False).encode())
        for rid, png in (crops or {}).items():
            url = (claim.get("crop_upload_urls") or {}).get(rid)
            if url:
                _put_bytes(url, png)
        _http_json("POST", f"{base}/api/jobs/{job_id}/result", key, payload)
        print(f"[session] job {job_id} done ({payload['gpu_seconds']}s)",
              flush=True)
        return "done"
    except (Exception, SystemExit) as exc:  # per-job fail → worker TIẾP (AC10)
        print(f"[session] job {job_id} LỖI: {exc}", flush=True)
        try:
            _http_json("POST", f"{base}/api/jobs/{job_id}/fail", key, {
                "error": f"session kernel: {exc}"[:500],
                "gpu_seconds": round(time.time() - t0, 2),
            })
        except Exception as post_exc:
            print(f"[session] job {job_id} fail-post lỗi: {post_exc}",
                  flush=True)
        return "failed"

def run_loop(base: str, key: str) -> int:
    start = time.monotonic()
    last_heartbeat = float("-inf")
    claim_retries = 0
    while True:
        now = time.monotonic()
        if now - start > SESSION_MAX_AGE_S - BUDGET_EXIT_MARGIN_S:
            print("[session] budget gần hết — exit 0", flush=True)
            return EXIT_GRACEFUL
        if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            _heartbeat(base, key)
            last_heartbeat = now
        try:
            claim = _http_json("GET", f"{base}/api/jobs/next", key)
        except urllib.error.HTTPError as exc:
            # 429 = limiter transient → backoff retry CÓ CAP; hết cap hoặc lỗi
            # khác (401 session đóng) → dừng sạch.
            if exc.code == 429 and claim_retries < CLAIM_MAX_RETRIES:
                claim_retries += 1
                delay = min(CLAIM_BACKOFF_MAX_S,
                            CLAIM_BACKOFF_BASE_S * 2 ** (claim_retries - 1))
                print(f"[session] claim 429 — backoff {delay:.0f}s "
                      f"({claim_retries}/{CLAIM_MAX_RETRIES})", flush=True)
                time.sleep(delay)
                continue
            print(f"[session] claim HTTP {exc.code} — exit 1", flush=True)
            return EXIT_FATAL
        claim_retries = 0
        if claim.get("empty"):
            print("[session] queue rỗng — exit 0", flush=True)
            return EXIT_GRACEFUL
        if (claim.get("server_flags") or {}).get("quota_low"):
            print("[session] quota_low — exit 0", flush=True)
            return EXIT_GRACEFUL
        run_job(base, key, claim)

def main() -> int:
    base = os.environ.get("BASE_URL")
    if not base:
        print("[session] thiếu BASE_URL (env hoặc bake __BASE_URL__ lúc push)",
              flush=True)
        return EXIT_FATAL
    if os.environ.get("_IMG2TEXT_SESSION_VENV") != "1":
        try:
            kb.bootstrap_venv()
        except (SystemExit, Exception) as exc:
            print(f"[session] bootstrap session-level fail: {exc}", flush=True)
            return EXIT_SESSION_LEVEL
        os.environ["_IMG2TEXT_SESSION_VENV"] = "1"
        os.execve(kb.VENV_PY, [kb.VENV_PY, __file__], os.environ)
        return EXIT_FATAL  # unreachable
    try:
        return run_loop(base, SESSION_KEY)
    except (Exception, SystemExit) as exc:
        print(f"[session] fatal: {exc}", flush=True)
        return EXIT_FATAL

if __name__ == "__main__":
    sys.exit(main())
