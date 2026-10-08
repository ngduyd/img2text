"""Runtime settings: DB Setting rows override env defaults (Plan S).

Admin UI edits land as Setting rows (key, value String) and take effect on the
next read — scheduler/orchestrator ticks read the override live, no restart.
Env (pydantic Settings) stays the default whenever the row is missing or does
not parse. Sessions come from `app.state.session_factory` (middleware
pattern); every caller is async (scheduler tick, orchestrator pass, admin API),
so no to_thread wrapper is needed.
"""

from app.core.config import settings
from app.core.models import Setting

# Keys served by GET /api/admin/settings (PUT covers the 3 numeric ones —
# kaggle_mode is read-only in the API: a mode flip mid-run would half-apply
# batch/loop state, so changing it needs a restart).
RUNTIME_SETTING_KEYS = (
    "scheduler_interval_seconds",
    "kaggle_min_queue",
    "kaggle_min_gap_seconds",
    "kaggle_mode",
    "llm_base_url",
    "llm_model",
    "proofread_llm_model",
    "llm_api_key",
)

def _parse(value: str, default):
    """Stored string → default's type; unparseable → default (env fallback)."""
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return value

async def _effective(session_factory, key: str, default) -> tuple:
    """(value, source) — source "db" iff a Setting row exists."""
    async with session_factory() as session:
        row = await session.get(Setting, key)
    if row is None:
        return default, "env"
    return _parse(row.value, default), "db"

async def get_runtime_setting_entry(session_factory, key: str) -> dict:
    """Effective `{value, source}` for the admin API."""
    value, source = await _effective(session_factory, key, getattr(settings, key))
    return {"value": value, "source": source}

async def get_runtime_setting(session_factory, key: str, default=None):
    """Effective value: DB Setting override, else the env/pydantic default."""
    if default is None:
        default = getattr(settings, key)
    value, _source = await _effective(session_factory, key, default)
    return value
