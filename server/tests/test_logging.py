"""#15 (spec 2026-10-15): RotatingFileHandler trong create_app.

maxBytes=100 + backupCount=3 (monkeypatch) — mỗi record >100 byte nên lần
log thứ 2 đã ROLLOVER: chứng minh rotation THẬT, không chỉ file tồn tại.
"""

import logging

from app.core.config import settings
from app.main import create_app


def test_log_rotation_config_applied(monkeypatch, tmp_path):
    log_file = tmp_path / "test.log"
    monkeypatch.setattr(settings, "log_path", str(log_file))
    monkeypatch.setattr(settings, "log_max_bytes", 100)
    monkeypatch.setattr(settings, "log_backup_count", 3)
    create_app()
    logger = logging.getLogger()
    for _ in range(6):
        logger.info("x" * 200)
    assert log_file.exists()
    backups = list(tmp_path.glob("test.log.*"))
    assert len(backups) >= 1  # rotation xảy ra (record > maxBytes)
    assert len(backups) <= 3  # backupCount cap


def test_create_app_replaces_handler_no_pileup(monkeypatch, tmp_path):
    """create_app() lặp (app fixture per-test) không xếp chồng handler —
    root chỉ có đúng 1 _img2text_rotating handler."""
    monkeypatch.setattr(settings, "log_path", str(tmp_path / "app.log"))
    create_app()
    create_app()
    ours = [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "_img2text_rotating", False)
    ]
    assert len(ours) == 1
