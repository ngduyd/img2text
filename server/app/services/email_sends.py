"""Wave-5 S5: per-kind outbound-email limits + send recording.

Mỗi kind (welcome | verify_code | reset_code) tính riêng per-user, rolling
24h trên bảng email_sends: max 5 lần; spacing send #1-3 gap ≥10 phút,
#4-5 gap ≥1 giờ (gap so với lần TRƯỚC trong window). Check TRƯỚC khi
record/enqueue — vượt → 429 flat body {code:"email_limit", retry_after_seconds}
(exception handler trong main.create_app map → JSONResponse).

Ponytail: count query per send (rate ~5/user/ngày) — upgrade when email
volume ever matters: Redis counter.
"""

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import EmailSend

DAILY_LIMIT = 5
WINDOW = timedelta(hours=24)
_SPACING_EARLY = timedelta(minutes=10)   # cho send #2-#3
_SPACING_LATE = timedelta(hours=1)       # cho send #4-#5

class EmailLimitExceeded(Exception):
    """429 {code:"email_limit", retry_after_seconds} — handler ở main.py."""

    def __init__(self, retry_after: timedelta) -> None:
        self.retry_after_seconds = max(1, math.ceil(retry_after.total_seconds()))
        super().__init__(f"email limit: retry in {self.retry_after_seconds}s")

async def check_limit(
    session: AsyncSession, user_id: int, kind: str
) -> None:
    """Quota check cho 1 lần gửi `kind`; vượt → raise EmailLimitExceeded."""
    now = datetime.now(timezone.utc)
    stamps = (
        (
            await session.execute(
                select(EmailSend.created_at)
                .where(
                    EmailSend.user_id == user_id,
                    EmailSend.kind == kind,
                    EmailSend.created_at > now - WINDOW,
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

def record(session: AsyncSession, user_id: int, kind: str) -> None:
    """Ghi audit row — caller commit cùng mutation của route, TRƯỚC khi
    enqueue background send (check_limit đã pass)."""
    session.add(EmailSend(user_id=user_id, kind=kind))
