"""Spec kaggle session worker T9a: config validator nhận "session" +
default flip "session" (batch giữ code — rollback = flip env)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

def test_kaggle_mode_session_parses():
    assert Settings(kaggle_mode="session").kaggle_mode == "session"

def test_kaggle_mode_batch_loop_still_parse():
    """Rollback/legacy parity — cả 2 giá trị cũ giữ nguyên."""
    assert Settings(kaggle_mode="batch").kaggle_mode == "batch"
    assert Settings(kaggle_mode="loop").kaggle_mode == "loop"

def test_kaggle_mode_bogus_rejected():
    with pytest.raises(ValidationError) as exc:
        Settings(kaggle_mode="bogus")
    assert "session, batch hoặc loop" in str(exc.value)

def test_kaggle_mode_default_is_session():
    assert Settings().kaggle_mode == "session"
