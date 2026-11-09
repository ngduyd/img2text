"""POST /api/jobs/sample — clone job mẫu cho user hiện tại.

Máy chưa có worker/GPU: job upload nằm `queued` mãi → người mới chỉ thấy empty
state. Endpoint này dựng 1 job `done` từ template do deploy/demo/seed.py đẩy lên
storage (chưa có template → 503 kèm hướng dẫn).
"""

import json

from sqlalchemy import func, select

from app.core.models import Job, OcrSuggestion

TEMPLATE = {
    "filename": "mau-de-thi.jpg",
    "file_type": "image",
    "page_count": 1,
    "storage_key": "uploads/mau.jpg",
    "upload_bytes": 1234,
    "result": {"pages": [{"regions": [{"id": "r1", "text": "Xin chào"}]}]},
    "suggestions": [
        {
            "page_index": 0,
            "start": 0,
            "end": 3,
            "original": "Xin",
            "suggestion": "Xin ",
            "reason": "khoảng trắng",
        }
    ],
}


async def test_sample_job_copies_template(auth_client, storage, db_session):
    await storage.put("demo/template.json", json.dumps(TEMPLATE).encode())
    r = await auth_client.post("/api/jobs/sample")
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]

    job = await db_session.get(Job, job_id)
    assert job.status == "done"
    assert job.filename == TEMPLATE["filename"]
    assert job.result == TEMPLATE["result"]
    assert job.finished_at is not None
    n = await db_session.scalar(
        select(func.count())
        .select_from(OcrSuggestion)
        .where(OcrSuggestion.job_id == job_id)
    )
    assert n == 1


async def test_sample_job_without_template_503(auth_client):
    r = await auth_client.post("/api/jobs/sample")
    assert r.status_code == 503
    assert "seed.py" in r.json()["detail"]
