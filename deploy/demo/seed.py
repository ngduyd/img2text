"""Seed dữ liệu demo: 1 tài khoản đã verify + 2 job `done` có kết quả OCR thật.

Vì sao: máy mới không có GPU (job upload sẽ nằm `queued` mãi) và DB trắng →
người xem chỉ thấy empty state. Seed này cho trang Jobs/Preview/Editor/Export
có nội dung ngay, không cần Kaggle.

Chạy (trong container server, đọc được /app/deploy):

    docker compose -f deploy/docker-compose.dev.yml exec -T server \
        python /app/deploy/demo/seed.py

Tài khoản: DEMO_EMAIL (mặc định demo@img2text.dev) / DEMO_PASSWORD
(mặc định demo-2024-pw). Idempotent: chạy lại = xoá job cũ của tài khoản demo
rồi tạo lại (không đụng job của user khác).
"""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.core.db import Base, SessionLocal, engine
from app.core.models import Job, OcrSuggestion, User
from app.core.security import hash_password
from app.services.storage import build_storage

HERE = Path(__file__).resolve().parent
DEMO_EMAIL = os.environ.get("DEMO_EMAIL", "demo@img2text.dev")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo-2024-pw")


async def _user(session) -> User:
    user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            role="user",
            ocr_enabled=True,          # quota/OCR gate cho user thường
            is_verified=True,          # không có SMTP trong demo → verify sẵn
            tos_accepted_at=datetime.now(timezone.utc),
        )
        session.add(user)
        await session.flush()
        print(f"tạo tài khoản demo {DEMO_EMAIL}")
    else:
        user.is_verified = True
        user.ocr_enabled = True
        print(f"dùng lại tài khoản demo {DEMO_EMAIL}")
    return user


async def _seed_job(session, storage, user: User, fixture_path: Path) -> int:
    fx = json.loads(fixture_path.read_text(encoding="utf-8"))
    image = fixture_path.parent / fx["image"]
    data = image.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    ext = fx["image"].rsplit(".", 1)[-1]
    key = f"uploads/{sha}.{ext}"
    if not await storage.exists(key):
        await storage.put(key, data)

    now = datetime.now(timezone.utc)
    job = Job(
        user_id=user.id,
        status="done",
        storage_key=key,
        filename=fx["filename"],
        file_type=fx["file_type"],
        page_count=fx["page_count"],
        output_format="docx",
        mode="layout",
        result=fx["result"],
        upload_bytes=len(data),
        text_version=1,
        created_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=2, minutes=-1),
    )
    session.add(job)
    await session.flush()
    for s in fx["suggestions"]:
        session.add(
            OcrSuggestion(
                job_id=job.id,
                page_index=s["page_index"],
                start=s["start"],
                end=s["end"],
                original=s["original"],
                suggestion=s["suggestion"],
                reason=s["reason"],
                status="pending",
            )
        )
    print(f"  job {job.id}: {fx['filename']} · {len(fx['suggestions'])} gợi ý sửa lỗi")
    return job.id


async def main() -> None:
    storage = build_storage()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)   # create_all không ALTER
    fixtures = sorted(p for p in HERE.glob("*.json") if p.name != "package.json")
    if not fixtures:
        sys.exit("không thấy fixture JSON nào trong deploy/demo/")
    async with SessionLocal() as session:
        user = await _user(session)
        # Chỉ dọn job của tài khoản demo — không đụng dữ liệu của user khác.
        old = (
            await session.execute(select(Job.id).where(Job.user_id == user.id))
        ).scalars().all()
        if old:
            await session.execute(
                delete(OcrSuggestion).where(OcrSuggestion.job_id.in_(old))
            )
            await session.execute(delete(Job).where(Job.id.in_(old)))
            print(f"xoá {len(old)} job cũ của tài khoản demo")
        ids = [await _seed_job(session, storage, user, p) for p in fixtures]
        await session.commit()
        # Template cho POST /api/jobs/sample (bản mẫu cấp cho user mới, không
        # cần GPU): lấy fixture đầu tiên.
        fx = json.loads(fixtures[0].read_text(encoding="utf-8"))
        tpl = {
            "filename": fx["filename"],
            "file_type": fx["file_type"],
            "page_count": fx["page_count"],
            "storage_key": f"uploads/{fx['sha256']}.{fx['image'].rsplit('.', 1)[-1]}",
            "upload_bytes": (fixtures[0].parent / fx["image"]).stat().st_size,
            "result": fx["result"],
            "suggestions": fx["suggestions"],
        }
        await storage.put(
            "demo/template.json",
            json.dumps(tpl, ensure_ascii=False).encode("utf-8"),
        )
    print(
        f"\nxong. đăng nhập {DEMO_EMAIL} / {DEMO_PASSWORD} → /jobs\n"
        f"mở trực tiếp: " + "  ".join(f"/jobs/{i}" for i in ids)
    )


asyncio.run(main())
