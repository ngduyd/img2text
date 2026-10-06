"""Plan K2: backend-orchestrated Kaggle worker spawn.

Server watches the queue: when queued jobs pile up and the last kernel run
is idle, push a fresh run (kernels push = upload + run). kernel/pipeline.py
loops forever on 204 backoff — a Kaggle session self-expires (~12h) and the
next spawn is a new run of the same kernel. Manual push (deploy/kaggle/
push.py, Plan K) only initialises dataset + kernel + Secrets once.

Flow per pass: disabled → skip; kernel active → skip; queued < min_queue
→ skip; spawn-gap → skip; stage kernel dir → datasets_create_version (kernel
executes DATASET code, not kernel-dir code — bump BEFORE push, fail → skip,
never spawn stale code) → kernels_push → record spawn time.

ponytail: async design — kaggle package is sync/blocking, so its calls run
via asyncio.to_thread; DB count uses the injected async session_factory
(middleware pattern). _last_spawn is per-process (single uvicorn worker by
design, same assumption as in-process rate limits); multi-worker deploy needs
a DB-backed spawn record.
"""

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.core.models import Job

logger = logging.getLogger(__name__)

DATASET_SLUG = "img2text-worker-files"
# kernel statuses meaning "run in progress" (case-insensitive match)
_ACTIVE_STATUSES = frozenset({"running", "pending", "queued"})

_last_spawn = 0.0


def _api():
    """Lazy kaggle import; missing package → None (disabled, no crash)."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        logger.warning(
            "kaggle package not installed — orchestration disabled "
            "(pip install 'server[kaggle]')"
        )
        return None
    api = KaggleApi()
    api.authenticate()
    return api


def _stage_src() -> Path:
    p = Path(settings.kaggle_stage_src)
    if not p.is_absolute():
        # default "deploy/kaggle" resolves against the repo root regardless
        # of cwd (server/app/services → parents[3])
        p = Path(__file__).resolve().parents[3] / p
    return p


def _sub_owner(obj, owner):
    if isinstance(obj, str):
        return obj.replace("OWNER", owner)
    if isinstance(obj, list):
        return [_sub_owner(x, owner) for x in obj]
    if isinstance(obj, dict):
        return {k: _sub_owner(v, owner) for k, v in obj.items()}
    return obj


def _kernel_slug() -> str:
    return settings.kaggle_kernel_ref.strip().split("/")[-1]


def _stage_kernel() -> Path:
    """Stage kernel dir from read-only templates: dataset files + notebook
    + generated metadata. Idempotent (fixed output names, overwritten);
    templates under stage_src are never written."""
    src = _stage_src()
    dest = Path(settings.kaggle_stage_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("pipeline.py", "verdict.py", "dataset-metadata.json"):
        shutil.copyfile(src / "files" / name, dest / name)
    shutil.copyfile(
        src / "kernel" / "img2text_worker.ipynb", dest / "img2text_worker.ipynb"
    )
    owner = settings.kaggle_username
    slug = _kernel_slug()
    meta = json.loads(
        (src / "kernel" / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    meta = _sub_owner(meta, owner)
    meta["id"] = f"{owner}/{slug}"
    meta["title"] = slug
    meta["code_file"] = "img2text_worker.ipynb"
    meta["dataset_sources"] = [f"{owner}/{DATASET_SLUG}"]
    meta["enable_gpu"] = True
    meta["enable_internet"] = True
    meta["machine_shape"] = settings.kaggle_accelerator
    meta["accelerator"] = settings.kaggle_accelerator
    (dest / "kernel-metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return dest


async def _count_queued(session_factory) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).where(Job.status == "queued")
        )
        return int(result.scalar_one())


async def ensure_worker(session_factory) -> bool:
    """Spawn a Kaggle kernel run when the queue needs it. True = pushed.

    Never raises: orchestration failures log a warning and return False
    (a broken Kaggle pass must not kill the scheduler job)."""
    global _last_spawn
    if not settings.kaggle_enabled:
        return False
    api = _api()
    if api is None:
        return False
    ref = settings.kaggle_kernel_ref.strip()
    try:
        resp = await asyncio.to_thread(api.kernels_status, ref)
        status = (
            resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None)
        )
        if str(status).lower() in _ACTIVE_STATUSES:
            logger.info("kaggle: kernel %s active (%s) — skip", ref, status)
            return False
        queued = await _count_queued(session_factory)
        if queued < settings.kaggle_min_queue:
            logger.info(
                "kaggle: queued=%d < min_queue=%d — skip",
                queued,
                settings.kaggle_min_queue,
            )
            return False
        now = time.monotonic()
        if now - _last_spawn < settings.kaggle_min_gap_seconds:
            logger.info(
                "kaggle: last spawn %.0fs ago < gap %ds — skip",
                now - _last_spawn,
                settings.kaggle_min_gap_seconds,
            )
            return False
        stage_dir = _stage_kernel()
        owner = settings.kaggle_username
        # P2 stale-code guard: kernel imports pipeline from the DATASET mount,
        # so bump the dataset version BEFORE pushing the kernel; bump failure
        # skips the spawn (pushing would run stale code).
        await asyncio.to_thread(
            api.datasets_create_version,
            f"{owner}/{DATASET_SLUG}",
            version_note=f"orchestrator spawn {int(time.time())}",
        )
        # P2: plain push — kernel-metadata.json carries the accelerator;
        # kernels_push timeout kw is unreliable (old packages lack push kwargs)
        # and inert for the session ceiling (platform-controlled).
        await asyncio.to_thread(api.kernels_push, str(stage_dir))
    except Exception:
        logger.warning("kaggle: ensure_worker failed", exc_info=True)
        return False
    _last_spawn = time.monotonic()
    logger.info("kaggle: spawned worker kernel %s from %s", ref, stage_dir)
    return True
