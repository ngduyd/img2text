from verdict import Region, SourceResult, normalize, resolve, similarity

def _r(text="Hello world", conf=None, is_image=False, ocr=None):
    src = {"vlm": SourceResult(text=text, confidence=None)}
    if ocr: src["ocr"] = SourceResult(*ocr)
    return Region(id="p1r0", bbox=(1, 2, 3, 4), sources=src, is_image=is_image)

def test_ok_vlm_only():
    assert resolve(_r(), "ok") == "ok"

def test_image_region_wins_over_unreadable_page():
    assert resolve(_r(text="", is_image=True), "unreadable") == "image_unextractable"

def test_unreadable_page_empty_text():
    assert resolve(_r(text=""), "unreadable") == "unreadable"

def test_low_confidence_page():
    assert resolve(_r(), "low_confidence") == "low_confidence"

def test_empty_vlm_on_ok_page_is_unreadable():
    assert resolve(_r(text=""), "ok") == "unreadable"

def test_dual_agree():
    assert resolve(_r(text="The cat sat.", ocr=("The cat sat.", 0.95)), "ok") == "ok"

def test_dual_ocr_preferred():
    assert resolve(_r(text="The car set.", ocr=("The cat sat.", 0.95)), "ok") == "ocr_preferred"

def test_dual_vlm_lowconf():
    assert resolve(_r(text="The cat sat.", ocr=("", 0.3)), "ok") == "vlm_lowconf"

def test_normalize_and_similarity():
    assert normalize("A. The Cat, sat!") == "a the cat sat"
    assert similarity("The cat sat", "the cat  sat") > 0.95
    assert similarity("", "") == 0.0

def test_zero_conf_means_untrustworthy():
    assert resolve(_r(text="x", ocr=("completely different text here", 0.0)), "ok") == "vlm_lowconf"
