"""Benchmark VLM→IR: đo độ chính xác cấu trúc + chi phí giữa các cách chia batch.

    cd server && .venv/bin/python scripts/ir_bench.py --variants A,B,C,D,E,F \
        --out /tmp/ir_bench_report.md

Env: IR_BENCH_BASE_URL (default http://localhost:20128/v1),
IR_BENCH_MODEL (default gh/gpt-4o-mini), IR_BENCH_API_KEY (fallback đọc
deploy/.env.dev dòng LLM_API_KEY — chỉ đọc, không in).

Variants: A per-page full payload, B per-page bỏ markdown, C per-page + bands
cluster từ layout_spec, D 1 call cả document, E chunk ≤30 region/call,
F baseline 0-call (IR dựng từ layout_spec, không LLM).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.services import ir, layout_spec  # noqa: E402
from scripts.ir_bench_score import flatten_ir, kendall_tau, order_of, score  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "layout_samples"
VARIANTS = ("A", "B", "C", "D", "E", "F")
CHUNK_REGIONS = 30
TIMEOUT = 120.0

def _api_key() -> str:
    key = (os.environ.get("IR_BENCH_API_KEY") or "").strip()
    if key:
        return key
    env_file = REPO / "deploy" / ".env.dev"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "LLM_API_KEY":
                return value.strip().strip('"').strip("'")
    return ""

def _content(resp: httpx.Response) -> str:
    """Gateway trả text/event-stream nhưng body là 1 JSON + `data: [DONE]`
    → raw_decode object đầu, bỏ phần đuôi."""
    text = resp.text.strip()
    start = text.find("{")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj["choices"][0]["message"]["content"]
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise RuntimeError(f"body lạ: {text[:200]!r}") from exc

def _post(base_url: str, model: str, key: str, prompt: str) -> str:
    """1 chat call + 1 retry. Trả raw content; raise RuntimeError kèm mã HTTP."""
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    last = ""
    for attempt in range(2):
        try:
            resp = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=body, headers=headers, timeout=TIMEOUT,
            )
            if resp.status_code != 200:
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
            else:
                return _content(resp)
        except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(last or "call fail")

def _strip_md(page: dict) -> dict:
    return {k: v for k, v in page.items() if k != "markdown"}

def _bands_payload(page: dict, spec: layout_spec.PageSpec) -> list[dict]:
    """Band cluster (layout_spec) + band giả cho region bị layout_spec nuốt
    (tab-stop) — giữ coverage công bằng khi so sánh."""
    out = [
        {
            "ids": [b.region_id for b in band],
            "bbox": [
                int(min(b.x0 for b in band)), int(min(b.y0 for b in band)),
                int(max(b.x1 for b in band)), int(max(b.y1 for b in band)),
            ],
            "col": band[0].col_index,
        }
        for band in layout_spec._bands(spec.blocks)
    ]
    seen = {b.region_id for b in spec.blocks}
    for region in page.get("regions", []):
        rid = str(region.get("id"))
        if rid in seen or not region.get("bbox"):
            continue
        out.append({"ids": [rid], "bbox": list(region["bbox"]), "col": -1})
    return out

class Runner:
    def __init__(self, base_url: str, model: str, key: str) -> None:
        self.base_url, self.model, self.key = base_url, model, key
        self.calls = 0
        self.ms = 0.0
        self.chars = 0

    def ask(self, prompt: str, what: str) -> dict:
        self.calls += 1
        self.chars += len(prompt)
        start = time.monotonic()
        try:
            return ir._parse_ir_json(_post(self.base_url, self.model, self.key, prompt), what)
        finally:
            self.ms += (time.monotonic() - start) * 1000

    def page_ir(self, page: dict, running_ctx: str) -> dict:
        prompt = (
            ir.IR_PROMPT_PAGE
            .replace("{running_ctx}", running_ctx or "(trống)")
            .replace("{ocr_json}", json.dumps(page, ensure_ascii=False))
        )
        return self.ask(prompt, "IR trang")

    def doc_ir(self, payload: dict) -> dict:
        prompt = ir.IR_PROMPT.replace("{ocr_json}", json.dumps(payload, ensure_ascii=False))
        return self.ask(prompt, "IR đầy đủ")

def _merge_pages(page_irs: list[dict]) -> dict:
    """Chunk/page IR object → document IR, merge theo page_number như
    ir.llm_ir_pages (id node prefix theo chunk để không trùng)."""
    merged: dict[int, dict] = {}
    for ci, page_ir in enumerate(page_irs):
        if "pages" in page_ir:
            page_ir = page_ir["pages"][0]
        number = int(page_ir.get("page_number") or 1)
        page = merged.setdefault(number, {
            "page_id": str(page_ir.get("page_id") or f"p{number}"),
            "page_number": number, "header": [], "content": [], "footer": [],
        })
        for section in ("header", "content", "footer"):
            for node in page_ir.get(section) or []:
                # id thiếu → để trống cho validate_ir tự assign (tránh trùng)
                node["id"] = f"c{ci}_{node['id']}" if node.get("id") else ""
                page[section].append(node)
    pages = [merged[n] for n in sorted(merged)]
    return {"document_id": "doc_001", "schema_version": "1.0", "pages": pages}

def _run_pages(run: Runner, result: dict, payload_of) -> dict:
    """Per-page loop với running §context (giống ir.llm_ir_pages)."""
    state, ctx, out = ir.AnchorState(), "", []
    for pi, page in enumerate(result.get("pages") or []):
        page_ir = run.page_ir(payload_of(page, pi), ctx)
        if "pages" in page_ir:
            return page_ir
        page_ir.setdefault("page_number", pi + 1)
        out.append(page_ir)
        line, state = ir._ctx_from_page(page, state)
        if line:
            ctx = (ctx + "\n" + line).strip()
    return _merge_pages(out)

def _run_spec(result: dict) -> dict:
    """Baseline 0-call: IR dựng trực tiếp từ layout_spec (type heuristic)."""
    out = []
    for pi, (page, spec) in enumerate(zip(result.get("pages") or [], layout_spec.build_page_specs(result))):
        nodes = []
        for block in spec.blocks:
            nodes.append({
                "id": f"f{pi}_{block.region_id}",
                "type": block.type_label,
                "source_block_ids": [block.region_id],
                "bbox": [round(v) for v in block.bbox],
            })
        seen = {b.region_id for b in spec.blocks}
        for region in page.get("regions") or []:   # region bị layout_spec nuốt (tab-stop)
            rid = str(region.get("id"))
            if rid in seen or not region.get("bbox"):
                continue
            nodes.append({"id": f"f{pi}_{rid}", "type": "paragraph",
                          "source_block_ids": [rid], "bbox": list(region["bbox"])})
        out.append({"page_id": str(page.get("index", pi)), "page_number": pi + 1,
                    "header": [], "content": nodes, "footer": []})
    return {"document_id": "doc_001", "schema_version": "1.0", "pages": out}

def _run_chunks(run: Runner, result: dict) -> dict:
    """Gom ≤30 region/call; trang lớn cắt giữa trang theo (y, x)."""
    chunks: list[dict] = []
    for pi, page in enumerate(result.get("pages") or []):
        regions = sorted(
            page.get("regions") or [], key=lambda r: ((r.get("bbox") or [0, 0])[1], (r.get("bbox") or [0, 0])[0])
        )
        for i in range(0, len(regions), CHUNK_REGIONS):
            part = _strip_md(page) | {"regions": regions[i:i + CHUNK_REGIONS]}
            chunks.append(part | {"page_number": pi + 1})
    out = [run.page_ir(chunk, "") for chunk in chunks]
    return _merge_pages(out)

def run_variant(run: Runner, variant: str, result: dict) -> dict:
    if variant == "A":
        return _run_pages(run, result, lambda page, pi: page)
    if variant == "B":
        return _run_pages(run, result, lambda page, pi: _strip_md(page))
    if variant == "C":
        specs = layout_spec.build_page_specs(result)

        def payload(page: dict, pi: int) -> dict:
            return _strip_md(page) | {"bands": _bands_payload(page, specs[pi])}

        return _run_pages(run, result, payload)
    if variant == "D":
        return run.doc_ir({"pages": [_strip_md(p) for p in result.get("pages") or []]})
    if variant == "E":
        return _run_chunks(run, result)
    if variant == "F":
        return _run_spec(result)
    raise ValueError(f"variant lạ: {variant}")

def load_samples(samples_dir: Path) -> list[tuple[str, dict, dict | None]]:
    """--samples có thể là 1 file .json hoặc 1 thư mục. Thiếu `.expected.json`
    → vẫn chạy, chấm cover/agreement (không có type_acc/order_acc)."""
    paths = [samples_dir] if samples_dir.is_file() else sorted(samples_dir.glob("*.json"))
    out = []
    for path in paths:
        if path.name.endswith(".expected.json"):
            continue
        expected_path = path.with_suffix("").with_suffix(".expected.json")
        expected = None
        if expected_path.exists():
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
        else:
            print(f"WARN: thiếu nhãn {expected_path.name} — chấm cover/agreement cho {path.name}",
                  file=sys.stderr)
        out.append((path.stem, json.loads(path.read_text(encoding="utf-8")), expected))
    return out

def _stat(values: list[float], digits: int = 2) -> str:
    """mean + min–max (gpt-4o-mini không tất định dù temperature=0)."""
    mean = sum(values) / len(values)
    lo, hi = min(values), max(values)
    text = f"{mean:.{digits}f}"
    return text if hi - lo < 10 ** -digits else f"{text} ({lo:.{digits}f}–{hi:.{digits}f})"

def _mean(reps: list[dict]) -> dict:
    """Gộp N lần chạy: coverage = passes/N, metric = mean (min–max)."""
    def vals(key: str) -> list[float]:
        return [float(r[key]) for r in reps]

    labeled = reps[0].get("type_acc") is not None
    return {
        "coverage": f"{sum(r['coverage_ok'] for r in reps)}/{len(reps)}",
        "type_acc": _stat(vals("type_acc")) if labeled else "—",
        "order_acc": _stat(vals("order_acc")) if labeled else "—",
        "extra_nodes": _stat(vals("extra_nodes")) if labeled else "—",
        "nodes": _stat(vals("nodes"), 0),
        "model_calls": _stat(vals("calls")),
        "ms": _stat(vals("ms"), 0),
        "chars": _stat(vals("chars"), 0),
    }

def _covers(ir_dict: dict, result: dict) -> bool:
    """Không có nhãn → chỉ kiểm tra IR dùng được (validate_ir)."""
    try:
        ir.validate_ir(ir_dict, result)
        return True
    except ir.IRValidationError:
        return False

def _agreement(orders: dict[tuple[str, str], list[list[str]]]) -> dict[tuple[str, str], list[float]]:
    """τ trung bình mỗi cặp variant (mọi cặp repeat của cùng sample)."""
    by_sample: dict[str, dict[str, list[list[str]]]] = {}
    for (sample, variant), runs in orders.items():
        by_sample.setdefault(sample, {})[variant] = runs
    out: dict[tuple[str, str], list[float]] = {}
    for sample, per_variant in by_sample.items():
        names = sorted(per_variant)
        for i, va in enumerate(names):
            for vb in names[i + 1:]:
                taus = [
                    kendall_tau(a, b)
                    for a in per_variant[va] for b in per_variant[vb]
                ]
                if taus:
                    out[(sample, f"{va}–{vb}")] = taus
    return out

def fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    ap.add_argument("--variants", default="A,B,C,D,E")
    ap.add_argument("--model", default=os.environ.get("IR_BENCH_MODEL", "gh/gpt-4o-mini"))
    ap.add_argument("--base-url", default=os.environ.get("IR_BENCH_BASE_URL", "http://localhost:20128/v1"))
    ap.add_argument("--repeat", type=int, default=5, help="số lần chạy mỗi (sample, variant) — lấy trung bình")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    key = _api_key()
    if not key:
        print("WARN: không có API key (IR_BENCH_API_KEY / deploy/.env.dev LLM_API_KEY)", file=sys.stderr)
    variants = [v.strip().upper() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        print(f"variant không hỗ trợ: {unknown}", file=sys.stderr)
        return 2

    rows, errors, orders = [], [], {}
    for sample, result, expected in load_samples(args.samples):
        for variant in variants:
            reps = []
            for _ in range(args.repeat):
                run = Runner(args.base_url, args.model, key)
                try:
                    ir_dict = run_variant(run, variant, result)
                    nodes = flatten_ir(ir_dict)
                    orders.setdefault((sample, variant), []).append(order_of(nodes))
                    if expected is None:
                        metrics = {"coverage_ok": _covers(ir_dict, result),
                                   "type_acc": None, "order_acc": None,
                                   "extra_nodes": None, "nodes": len(nodes)}
                    else:
                        m = score(ir_dict, expected, result)
                        metrics = {"coverage_ok": m["coverage_ok"], "type_acc": m["type_acc"],
                                   "order_acc": m["order_acc"], "extra_nodes": m["extra_nodes"],
                                   "nodes": len(nodes)}
                    error = ""
                except Exception as exc:  # HTTP/parse fail → ghi rõ, không bỏ im
                    metrics = {"coverage_ok": False, "type_acc": None, "order_acc": None,
                               "extra_nodes": None, "nodes": 0}
                    error = f"{type(exc).__name__}: {exc}"
                    errors.append(f"{sample}/{variant}: {error}")
                reps.append({
                    "coverage_ok": metrics["coverage_ok"],
                    "type_acc": metrics["type_acc"], "order_acc": metrics["order_acc"],
                    "extra_nodes": metrics["extra_nodes"], "nodes": metrics["nodes"],
                    "calls": run.calls, "ms": run.ms, "chars": run.chars, "error": error,
                })
                print(
                    f"{sample:6} {variant} cover={metrics['coverage_ok']!s:5} "
                    f"nodes={metrics['nodes']} calls={run.calls} "
                    f"ms={run.ms:.0f} chars={run.chars}"
                    + (f" type={fmt(metrics['type_acc'])} order={fmt(metrics['order_acc'])}"
                       f" extra={metrics['extra_nodes']}" if expected is not None else "")
                    + (f" ERROR {error}" if error else ""),
                    file=sys.stderr,
                )
            rows.append({"sample": sample, "variant": variant, **_mean(reps)})

    lines = [
        "# IR benchmark (VLM→IR)",
        "",
        f"model=`{args.model}` base_url=`{args.base_url}` samples=`{args.samples.name}` "
        f"repeat=`{args.repeat}`",
        "",
        "coverage = số lần pass/N; các ô khác = mean (min–max).",
        "",
        "| sample | variant | coverage | type_acc | order_acc | extra | nodes | model_calls | ms | chars |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['sample']} | {row['variant']} | {row['coverage']} "
            f"| {row['type_acc']} | {row['order_acc']} | {row['extra_nodes']} "
            f"| {row['nodes']} | {row['model_calls']} | {row['ms']} | {row['chars']} |"
        )
    agree = _agreement(orders)
    if agree:
        lines += ["", "## Agreement — Kendall τ thứ tự đọc giữa các cặp variant",
                  "", "| sample | pair | τ |", "|---|---|---|"]
        lines += [f"| {s} | {p} | {_stat(v)} |" for (s, p), v in agree.items()]
    if errors:
        lines += ["", "## Lỗi", ""] + [f"- {e}" for e in errors]
    report = "\n".join(lines) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"report → {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
