"""Temporary admin-only probe route (Task 8).

# ponytail: Plan E Task 1 replaces this file with the real admin router;
# keep only require_admin wiring until then.
"""

from fastapi import APIRouter, Depends

from app.deps import get_current_user, require_admin
from app.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _admin_user(user: User = Depends(get_current_user)) -> User:
    return require_admin(user)


@router.get("/__probe")
async def probe(_: User = Depends(_admin_user)) -> dict[str, bool]:
    return {"ok": True}
