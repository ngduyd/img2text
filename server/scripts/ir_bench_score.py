"""Scoring thuần hàm cho benchmark VLM→IR (không network, test offline).

Region-level: mỗi `region_id` được chấm theo type của IR node chứa nó và theo
vị trí của nó trong thứ tự đọc — LLM merge/split node không bị fail oan.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ir import IRValidationError, validate_ir  # noqa: E402

SECTIONS = ("header", "content", "footer")

def _walk(node: dict, out: list[dict]) -> None:
    out.append(node)
    for child in node.get("children") or []:
        _walk(child, out)

def flatten_ir(ir: dict) -> list[dict]:
    """Nodes theo thứ tự đọc: page → header, content, footer → children DFS."""
    out: list[dict] = []
    pages = sorted(ir.get("pages") or [], key=lambda p: p.get("page_number") or 0)
    for page in pages:
        for section in SECTIONS:
            for node in page.get(section) or []:
                _walk(node, out)
    return out

def _region_ids(node: dict) -> list[str]:
    return [str(b) for b in (node.get("source_block_ids") or [])]

def _expected_regions(expected: dict) -> list[tuple[str, str]]:
    """[(region_id, kỳ vọng type)] theo thứ tự đọc kỳ vọng."""
    out: list[tuple[str, str]] = []
    for node in expected.get("nodes") or []:
        ids = node.get("ids") or []
        if isinstance(ids, str):
            ids = [ids]
        out.extend((str(b), str(node.get("type"))) for b in ids)
    return out

def _type_map(nodes: list[dict]) -> dict[str, str]:
    """region_id → type của node ĐẦU TIÊN chứa nó (LLM lặp id → lấy node đầu)."""
    out: dict[str, str] = {}
    for node in nodes:
        for rid in _region_ids(node):
            out.setdefault(rid, str(node.get("type")))
    return out

def _inversions(seq: list[int]) -> tuple[int, int]:
    pairs = total = 0
    for i in range(len(seq)):
        for j in range(i + 1, len(seq)):
            total += 1
            if seq[i] > seq[j]:
                pairs += 1
    return pairs, total

def order_of(nodes: list[dict]) -> list[str]:
    """Danh sách region_id theo thứ tự đọc IR (dedup, giữ lần đầu)."""
    out: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        for rid in _region_ids(node):
            if rid not in seen:
                seen.add(rid)
                out.append(rid)
    return out

def score(ir: dict, expected: dict, result: dict) -> dict:
    """coverage/type_acc/order_acc/extra_nodes. coverage fail → không chấm
    type/order (đặt 0) vì IR không dùng được."""
    try:
        validate_ir(ir, result)
        coverage_ok = True
    except IRValidationError:
        coverage_ok = False

    regions = _expected_regions(expected)
    nodes = flatten_ir(ir)
    types = _type_map(nodes)

    if coverage_ok:
        hits = sum(1 for rid, want in regions if types.get(rid) == want)
        type_acc = hits / len(regions) if regions else 1.0
        rank = {rid: i for i, (rid, _) in enumerate(regions)}
        seq = [rank[rid] for rid in order_of(nodes) if rid in rank]
        pairs, total = _inversions(seq)
        order_acc = 1.0 - pairs / total if total else 1.0
    else:
        type_acc = order_acc = 0.0

    known = {rid for rid, _ in regions}
    extra_nodes = sum(1 for node in nodes if not (set(_region_ids(node)) & known))
    return {
        "coverage_ok": coverage_ok,
        "type_acc": type_acc,
        "order_acc": order_acc,
        "extra_nodes": extra_nodes,
        "regions": len(regions),
    }
