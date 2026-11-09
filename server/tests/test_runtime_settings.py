
async def test_parse_bool_default_accepts_true_string():
    """Bug thật: bool là subclass của int → 'true' rơi vào nhánh int, ValueError →
    luôn trả default False (kaggle_batch_predict không bật được từ DB)."""
    from app.services.runtime_settings import _parse

    assert _parse("true", False) is True
    assert _parse("1", False) is True
    assert _parse("off", False) is False
    assert _parse("false", True) is False
    assert _parse("12", 5) == 12          # int vẫn như cũ
