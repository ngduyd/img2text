"""Wave-5 S5: per-kind outbound-email limits + DB-backed email outbox.

Mỗi kind (welcome | verify_code | reset_code) tính riêng per-user, rolling
24h trên bảng email_sends: max 5 lần; spacing send #1-3 gap ≥10 phút,
#4-5 gap ≥1 giờ (gap so với lần TRƯỚC trong window). Check TRƯỚC khi
enqueue — vượt → 429 flat body {code:"email_limit", retry_after_seconds}
(exception handler trong main.create_app map → JSONResponse).

Outbox (2026-10-20): route enqueue row (status='queued'), scheduler job
`flush-email-outbox` gọi drain() → gửi qua mailer. SMTP fail không còn 503:
retry backoff, 3 lần → status='failed' (refund quota, row giữ làm audit).

Ponytail: count query per send (rate ~5/user/ngày) — upgrade when email
volume ever matters: Redis counter.
"""

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import EmailSend
from app.services import mailer

DAILY_LIMIT = 5
WINDOW = timedelta(hours=24)
_SPACING_EARLY = timedelta(minutes=10)   # cho send #2-#3
_SPACING_LATE = timedelta(hours=1)       # cho send #4-#5

MAX_ATTEMPTS = 3          # 3 lần fail → 'failed' (refund quota, giữ audit)
_BACKOFF_BASE = 60        # giây; ×2 mỗi attempt
_BACKOFF_MAX = 15 * 60    # trần 900s
_RECLAIM_AFTER = timedelta(minutes=5)  # lease của 'sending' (crash) → queued lại

class EmailLimitExceeded(Exception):
    """429 {code:"email_limit", retry_after_seconds} — handler ở main.py."""

    def __init__(self, retry_after: timedelta) -> None:
        self.retry_after_seconds = max(1, math.ceil(retry_after.total_seconds()))
        super().__init__(f"email limit: retry in {self.retry_after_seconds}s")

async def check_limit(
    session: AsyncSession, user_id: int, kind: str
) -> None:
    """Quota check cho 1 lần gửi `kind`; vượt → raise EmailLimitExceeded.

    Row status='failed' KHÔNG tính (refund quota — user chưa nhận mail)."""
    now = datetime.now(timezone.utc)
    stamps = (
        (
            await session.execute(
                select(EmailSend.created_at)
                .where(
                    EmailSend.user_id == user_id,
                    EmailSend.kind == kind,
                    EmailSend.created_at > now - WINDOW,
                    EmailSend.status != "failed",
                )
                .order_by(EmailSend.created_at)
            )
        )
        .scalars()
        .all()
    )
    if len(stamps) >= DAILY_LIMIT:
        raise EmailLimitExceeded(stamps[0] + WINDOW - now)
    if stamps:
        # lần sắp gửi #(len+1): từ #4 trở đi cần gap 1h
        gap = _SPACING_LATE if len(stamps) + 1 >= 4 else _SPACING_EARLY
        retry_after = stamps[-1] + gap - now
        if retry_after > timedelta(0):
            raise EmailLimitExceeded(retry_after)

def enqueue(
    session: AsyncSession,
    user_id: int,
    kind: str,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    """Queue 1 email (caller commit) — check_limit đã pass TRƯỚC (chặn burst).
    Gửi thật do drain() trong scheduler; route không chờ SMTP."""
    session.add(
        EmailSend(
            user_id=user_id,
            kind=kind,
            to_email=to_email,
            subject=subject,
            body=body,
        )
    )

async def drain(session: AsyncSession, limit: int = 20) -> tuple[int, int]:
    """Gửi email đang due; trả (sent, failed). Mỗi row commit riêng → 1 row
    fail không chặn row sau. Claim nguyên tử (UPDATE ... WHERE status='queued')
    commit TRƯỚC send → 2 pass đồng thời không gửi trùng.

    Khi status='sending', `next_attempt_at` đóng vai trò LEASE DEADLINE: claim
    set next_attempt_at = now + _RECLAIM_AFTER, reclaim chỉ nhặt row 'sending'
    có next_attempt_at < now (lease hết hạn = crash giữa send) về 'queued'.
    Không set lease lúc claim thì row due từ lâu sẽ bị reclaim ngay trong lúc
    send đang bay → gửi trùng.

    Row xử lý xong ở trạng thái TERMINAL ('sent' / 'failed') bị xoá `body`:
    mã 6 số không được nằm at-rest sau khi gửi (DB dump/backup leak = chiếm
    tài khoản). Row 'queued' (kể cả retry-queued) và 'sending' GIỮ body —
    body là plaintext chứa mã 6 số, chỉ được at-rest cho tới lần retry cuối
    (≤ ~3 phút với backoff hiện tại); terminal → redact."""
    now = datetime.now(timezone.utc)
    ids = (
        (
            await session.execute(
                select(EmailSend.id)
                .where(
                    EmailSend.status == "queued",
                    EmailSend.next_attempt_at <= now,
                )
                .order_by(EmailSend.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    sent = failed = 0
    for row_id in ids:
        claimed = (
            await session.execute(
                update(EmailSend)
                .where(EmailSend.id == row_id, EmailSend.status == "queued")
                .values(
                    status="sending",
                    # lease: reclaim pass khác không nhặt lại khi đang send
                    next_attempt_at=now + _RECLAIM_AFTER,
                )
                .returning(
                    EmailSend.to_email,
                    EmailSend.subject,
                    EmailSend.body,
                    EmailSend.attempts,
                )
            )
        ).one_or_none()
        await session.commit()  # claim visible → pass khác skip
        if claimed is None:  # pass khác đã claim
            continue
        ok, err = await mailer.send_email(
            claimed.to_email or "", claimed.subject or "", claimed.body or ""
        )
        if ok:
            values: dict = {
                "status": "sent",
                "sent_at": datetime.now(timezone.utc),
                "last_error": None,
                "body": None,  # mã 6 số không được nằm at-rest sau khi gửi
            }
            sent += 1
        else:
            attempts = claimed.attempts + 1
            backoff = min(_BACKOFF_BASE * 2**attempts, _BACKOFF_MAX)
            terminal = attempts >= MAX_ATTEMPTS
            values = {
                "status": "failed" if terminal else "queued",
                "attempts": attempts,
                "last_error": (err or "unknown error")[:500],
                "next_attempt_at": datetime.now(timezone.utc)
                + timedelta(seconds=backoff),
            }
            if terminal:  # retry-queued giữ body để lần gửi sau đúng nội dung
                values["body"] = None  # mã 6 số không được nằm at-rest
            failed += 1
        await session.execute(
            update(EmailSend).where(EmailSend.id == row_id).values(**values)
        )
        await session.commit()

    # lease hết hạn (crash giữa send) → queued; next_attempt_at = lease deadline
    now = datetime.now(timezone.utc)
    await session.execute(
        update(EmailSend)
        .where(
            EmailSend.status == "sending",
            EmailSend.sent_at.is_(None),
            EmailSend.next_attempt_at < now,
        )
        .values(status="queued")
    )
    await session.commit()
    return sent, failed
