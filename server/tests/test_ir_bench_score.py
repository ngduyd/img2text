"""Offline tests cho scoring VLM→IR (không network). Region-level."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.services.ir import IRValidationError, validate_ir
from scripts.ir_bench_score import kendall_tau, score

FIXTURES = Path(__file__).parent / "fixtures" / "layout_samples"

def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))

def _node(nid: str, ntype: str, ids: list[str]) -> dict:
    return {"id": nid, "type": ntype, "source_block_ids": list(ids), "bbox": [0, 0, 1, 1]}

def _ir(nodes: list[dict]) -> dict:
    return {
        "document_id": "doc_001",
        "schema_version": "1.0",
        "pages": [{
            "page_id": "p1", "page_number": 1,
            "header": [], "content": nodes, "footer": [],
        }],
    }

def _base_ir() -> dict:
    return _ir([
        _node("n0", "heading", ["r0"]),
        _node("n1", "heading", ["r1"]),
        _node("n2", "paragraph", ["r2"]),
        _node("n3", "paragraph", ["r3"]),
        _node("n5", "paragraph", ["r5"]),
        _node("n4", "figure", ["r4"]),
    ])

@pytest.fixture
def result() -> dict:
    return _load("1col")

@pytest.fixture
def expected() -> dict:
    return json.loads((FIXTURES / "1col.expected.json").read_text(encoding="utf-8"))

def test_perfect_ir_scores_1(result: dict, expected: dict) -> None:
    s = score(_base_ir(), expected, result)
    assert s["coverage_ok"] is True
    assert s["type_acc"] == 1.0
    assert s["order_acc"] == 1.0
    assert s["extra_nodes"] == 0

def test_swapped_regions_lower_order(result: dict, expected: dict) -> None:
    ir = _base_ir()
    content = ir["pages"][0]["content"]
    content[2], content[3] = content[3], content[2]   # r3 trước r2
    s = score(ir, expected, result)
    assert s["coverage_ok"] is True
    assert s["type_acc"] == 1.0          # đảo thứ tự không đổi type
    assert s["order_acc"] == pytest.approx(1 - 1 / 15)  # 6 region → 15 cặp
    assert s["extra_nodes"] == 0

def test_merge_tolerated_but_wrong_type_counted(result: dict, expected: dict) -> None:
    """LLM merge r2+r3 thành 1 node: chấm theo region, type sai vẫn bị đếm."""
    ir = _ir([
        _node("n0", "heading", ["r0"]),
        _node("n1", "heading", ["r1"]),
        _node("n2", "paragraph", ["r2", "r3"]),
        _node("n5", "paragraph", ["r5"]),
        _node("n4", "figure", ["r4"]),
    ])
    s = score(ir, expected, result)
    assert s["coverage_ok"] is True
    assert s["type_acc"] == 1.0          # cả r2 và r3 đều paragraph → đúng
    ir["pages"][0]["content"][2] = _node("n2", "heading", ["r2", "r3"])
    s = score(ir, expected, result)
    assert s["type_acc"] == pytest.approx(4 / 6)

def test_node_without_region_counts_extra(result: dict, expected: dict) -> None:
    ir = _base_ir()
    ir["pages"][0]["content"].append(_node("n9", "paragraph", []))
    s = score(ir, expected, result)
    assert s["coverage_ok"] is True
    assert s["type_acc"] == 1.0
    assert s["extra_nodes"] == 1

def test_missing_block_fails_coverage(result: dict, expected: dict) -> None:
    ir = _base_ir()
    del ir["pages"][0]["content"][3]        # r3 biến mất → coverage âm
    with pytest.raises(IRValidationError):
        validate_ir(copy.deepcopy(ir), result)
    s = score(ir, expected, result)
    assert s["coverage_ok"] is False
    assert s["type_acc"] == 0.0
    assert s["order_acc"] == 0.0

# ---------------------------------------------------------------- kendall_tau

def test_tau_identical_and_reversed() -> None:
    a = ["x", "y", "z"]
    assert kendall_tau(a, a) == 1.0
    assert kendall_tau(a, ["z", "y", "x"]) == -1.0

def test_tau_one_swap_and_partial_overlap() -> None:
    assert kendall_tau(["x", "y", "z"], ["x", "z", "y"]) == pytest.approx(1 / 3)
    # id chỉ có ở một phía bị bỏ; 2 id chung → 1 cặp
    assert kendall_tau(["x", "y", "q"], ["y", "x"]) == -1.0
    assert kendall_tau(["x"], ["x", "y"]) == 1.0
