import json
from pathlib import Path

from pipeline import build_page, build_result, page_markdown_from, res_json_to_regions

def load_fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())

def test_adapter_maps_regions():
    regions = res_json_to_regions(load_fixture("res_json_canned.json"))
    assert [r.id for r in regions] == ["p1r0", "p1r1", "p1r2", "p1r3"]
    assert regions[2].is_image and regions[2].bbox is not None

def test_page_markdown_structure_fidelity():
    fx = load_fixture("res_json_canned.json")
    regions = res_json_to_regions(fx)
    md = page_markdown_from(fx, regions, "ok", 1)
    assert "## Midterm Test" in md                       # title → ##
    assert "5. A. cat B. car C. cap D. can" in md        # numbering verbatim
    assert "| Q1 |" in md                                # table pipes preserved
    assert "**[Hình ảnh chưa trích xuất: vùng p1r2]**" in md  # marker replaces placeholder token

def test_build_result_shape_matches_spec():
    fx = load_fixture("res_json_canned.json")
    page = build_page(fx, 1, inference_ran=True)
    result = build_result([page], gpu_seconds=12.5)
    assert set(result) >= {"model_version", "gpu_seconds", "warnings", "markdown", "pages"}
    assert result["model_version"] == "PaddleOCR-VL-1.5-0.9B"
    assert result["gpu_seconds"] == 12.5
    assert page["regions"][0]["verdict"] in {"ok", "image_unextractable", "unreadable", "low_confidence"}
    assert page["regions"][0]["bbox"] == [1, 2, 3, 4]

def test_unreadable_page_skips_inference():
    fx = load_fixture("res_json_canned.json")
    page = build_page(fx, 3, inference_ran=False)   # precheck both-fail path
    assert page["page_flag"] == "unreadable"
    assert page["regions"] == []
    assert "Không trích xuất được văn bản" in page["markdown"]
