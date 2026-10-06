"""Plan K2: backend-orchestrated Kaggle worker spawn.

Server watches the queue: when queued jobs pile up and the last kernel run
is idle, push a fresh run (kernels push = upload + run). kernel/pipeline.py
loops forever on 204 backoff — a Kaggle session self-expires (~12h) and the
next spawn is a new run of the same kernel. Manual push (deploy/kaggle/
push.py, Plan K) only initialises dataset + kernel + Secrets once.

Flow per pass: disabled → skip; kernel active → skip; queued < min_queue
→ skip; spawn-gap → skip; stage kernel dir → dataset version bump (kernel
executes DATASET code, not kernel-dir code — bump BEFORE push, fail → skip,
never spawn stale code) → kernels_push → record spawn time. The bump sends
the STAGED FOLDER (worker files + dataset-metadata.json) so kaggle 2.2.4's
folder-based dataset_create_version uploads fresh files — kaggle>=2 renamed
the API, dispatch is hasattr-based inline in _bump_dataset_version (server
cannot import deploy/kaggle/kcompat).

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


def _normalize_licenses(licenses):
    """kaggle 2.2.4 dataset-metadata needs [{"name": ...}] dicts (old
    shape was plain strings — create fails: 'Key name not found in data')."""
    return [
        lic if isinstance(lic, dict) else {"name": lic} for lic in licenses
    ]

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
    # dataset-metadata.json: the staged dir doubles as the dataset-upload
    # folder for the pre-push version bump — kaggle 2.2.4 requires "id" there
    ds_meta = json.loads(
        (src / "files" / "dataset-metadata.json").read_text(encoding="utf-8")
    )
    ds_meta["id"] = f"{owner}/{DATASET_SLUG}"
    ds_meta["licenses"] = _normalize_licenses(ds_meta.get("licenses", []))
    (dest / "dataset-metadata.json").write_text(
        json.dumps(ds_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return dest

def _bump_dataset_version(api, owner, folder, notes):
    """Dataset version bump — kaggle 2.2.4 renamed the API (hasattr dispatch).

    new: dataset_create_version(folder, version_notes) uploads from the
    staged folder; legacy: datasets_create_version(owner, slug, version_note).
    """
    if hasattr(api, "dataset_create_version"):
        return api.dataset_create_version(str(folder), notes)
    if hasattr(api, "datasets_create_version"):
        slug = DATASET_SLUG
        return api.datasets_create_version(owner, slug, version_note=notes)
    raise RuntimeError(
        "kaggle package: dataset_create_version not found — cần kaggle>=1.6"
    )


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
    ref = settings.kaggle_kernel_ref.strip()
    try:
        api = _api()  # inside try: constructor/auth errors must also return False (never-raise contract)
        if api is None:
            return False
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
        # skips the spawn (pushing would run stale code). The staged folder
        # carries worker files + dataset-metadata.json (id set in _stage_kernel).
        await asyncio.to_thread(
            _bump_dataset_version,
            api,
            owner,
            stage_dir,
            f"orchestrator spawn {int(time.time())}",
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
