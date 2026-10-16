"""P2 #20 (spec 2026-10-16): feedback + upload rate limits (per-user).

App mới per test (conftest `app` fixture function-scoped) → limiter state
sạch giữa các test, không cần reset.
"""

FEEDBACK = {"content": "test"}
JOB = {"storage_key": "uploads/deadbeef-cafe.jpg", "page_count": 1}

async def test_rate_limit_feedback_exceeded(auth_client):
    """10 feedback/phút per user — lần 11 → 429."""
    last = None
    for _ in range(11):
        last = await auth_client.post("/api/feedback", json=FEEDBACK)
    assert last.status_code == 429

async def test_rate_limit_upload_exceeded(auth_client, monkeypatch):
    """30 upload/giờ per user — lần 31 → 429. Daily counter (20/ngày) đẩy
    lên 999 để KHÔNG chặn trước — test đo đúng limiter HOURLY mới."""
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router, "UPLOAD_DAILY_LIMIT", 999)
    last = None
    for _ in range(31):
        last = await auth_client.post("/api/jobs", json=JOB)
    assert last.status_code == 429

async def test_rate_limit_passes_under_limit(auth_client):
    """Dưới hạn mức → không 429 (feedback + upload mỗi endpoint 1 request)."""
    r = await auth_client.post("/api/feedback", json=FEEDBACK)
    assert r.status_code != 429
    r = await auth_client.post("/api/jobs", json=JOB)
    assert r.status_code != 429
