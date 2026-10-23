"""Guard OCR: tất định, 0 LLM — chỉ warning, không sửa result."""

from __future__ import annotations

import pytest

from app.services.ocr_guards import check_result

pytestmark = pytest.mark.nodb


def _page(regions: list[dict], width: int = 800, height: int = 1000) -> dict:
    return {"index": 0, "width": width, "height": height, "page_flag": "ok",
            "markdown": "", "regions": regions}


def _r(rid: str, text: str, bbox: list[int], verdict: str = "ok") -> dict:
    return {"id": rid, "bbox": bbox, "text": text, "verdict": verdict,
            "placeholder": False}


def _kinds(warns: list[str]) -> list[str]:
    return [w.split(":")[1] for w in warns]


def test_clean_page_no_warning():
    regions = [
        _r(f"r{i}", f"Đoạn văn bản bình thường số {i} " * 2,
           [60, 100 + i * 60, 700, 150 + i * 60])
        for i in range(5)
    ]
    # trang 800×1000, region 640×50 → 5 region ≈ 20% diện tích → không low_coverage
    assert check_result({"pages": [_page(regions)]}) == []


def test_density_outlier_flagged():
    ok = "Đoạn văn bản bình thường dài vừa phải " * 2
    regions = [_r(f"r{i}", ok, [60, 100 + i * 60, 700, 150 + i * 60]) for i in range(4)]
    regions.append(_r("r9", "x" * 2000, [60, 500, 700, 550]))   # loop decode
    warns = check_result({"pages": [_page(regions)]})
    assert "density" in _kinds(warns), warns


def test_empty_region_flagged():
    regions = [
        _r("r0", "", [10, 10, 400, 400]),          # 16% trang, rỗng
        _r("r1", "chữ bình thường", [60, 500, 700, 550]),
    ]
    assert "empty_region" in _kinds(check_result({"pages": [_page(regions)]}))


def test_duplicate_text_same_page_flagged():
    line = "Dòng bị lặp lại nhiều lần"
    regions = [_r(f"r{i}", line, [60, 100 + i * 60, 700, 150 + i * 60]) for i in range(3)]
    regions.append(_r("r9", "dòng khác hoàn toàn", [60, 400, 700, 450]))
    assert "dup_text" in _kinds(check_result({"pages": [_page(regions)]}))


def test_duplicate_across_pages_not_flagged():
    """Header/footer lặp giữa các trang là hợp lệ."""
    line = "TRƯỜNG THPT NGUYỄN DU"
    pages = [_page([_r(f"p{p}_r0", line, [60, 20, 700, 60])]) for p in range(4)]
    assert "dup_text" not in _kinds(check_result({"pages": pages}))


def test_bbox_outside_page_flagged():
    regions = [
        _r("r0", "chữ", [60, 100, 700, 150]),
        _r("r1", "chữ", [60, 700, 1600, 900]),      # x2 > width
    ]
    assert "bbox_out" in _kinds(check_result({"pages": [_page(regions)]}))


def test_bbox_overlap_flagged():
    regions = [
        _r("r0", "một đoạn văn", [60, 100, 700, 200]),
        _r("r1", "một đoạn văn", [62, 102, 698, 198]),   # IoU > 0.8
    ]
    assert "bbox_overlap" in _kinds(check_result({"pages": [_page(regions)]}))


def test_low_coverage_flagged():
    regions = [_r("r0", "chỉ một dòng nhỏ", [60, 100, 200, 120])]
    assert "low_coverage" in _kinds(check_result({"pages": [_page(regions)]}))


def test_low_confidence_verdict_flagged():
    regions = [
        _r("r0", "chữ", [60, 100, 700, 150], verdict="low_confidence"),
        _r("r1", "chữ", [60, 200, 700, 250]),
    ]
    warns = check_result({"pages": [_page(regions)]})
    assert "low_conf" in _kinds(warns), warns


def test_guard_appends_to_warnings_on_ingest():
    """_with_guards: warning cũ giữ nguyên, guard nối thêm."""
    from app.core.schemas import ResultBody

    body = ResultBody(
        model_version="m", gpu_seconds=0.0, warnings=["worker: cảnh báo cũ"],
        markdown="", pages=[_page([_r("r0", "chỉ một dòng nhỏ", [60, 100, 200, 120])])],
    )
    from app.services.job_results import _with_guards

    payload = _with_guards(body)
    assert payload["warnings"][0] == "worker: cảnh báo cũ"
    assert any(":low_coverage:" in w for w in payload["warnings"])
