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

Plan K5 (kaggle_mode=batch, default): ensure_worker dispatches — batch mode
stages the queued job's upload as the img2text-input dataset (delete+create),
pushes the standalone script kernel (deploy/kaggle/img2text_batch.py), polls
status, pulls result.json and ingests it into the job. No public URL needed.
Runs live in the in-memory _batch_runs map (restart = orphan kernel ceiling —
no DB column); "loop" keeps the Plan K2 branch above untouched.
"""

import asyncio
import json
import logging
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.models import Job
from app.core.schemas import ResultBody
from app.services.job_results import store_batch_result
from app.services.runtime_settings import get_runtime_setting

logger = logging.getLogger(__name__)

DATASET_SLUG = "img2text-worker-files"
INPUT_SLUG = "img2text-input"  # batch input dataset (run_one.py K4, shared slug)
# kernel statuses meaning "run in progress" (case-insensitive match)
_ACTIVE_STATUSES = frozenset({"running", "pending", "queued"})
# batch statuses meaning "terminal" (normalized lowercase)
_FAILED_STATUSES = frozenset({"failed", "error"})
# mirrors kernel VL_MODEL / worker build_result default (result.json has no version)
BATCH_MODEL_VERSION = "PaddleOCR-VL-1.5-0.9B"
# per-block markdown prefixes (batch doc_title → H1, paragraph_title → H2;
# table/text → raw — block.text is already HTML for tables)
_MD_PREFIX = {"doc_title": "# ", "paragraph_title": "## "}

_last_spawn = 0.0
# ceiling: persistent ingest failures for one ref → drop instead of looping
_INGEST_MAX_FAILURES = 3
# Plan K5 batch runs: {job_id: {"ref": str, "pushed_at": monotonic}}.
# In-memory only (non-goal: no DB column) — restart orphans a running kernel.
_batch_runs: dict[int, dict] = {}
# input-dataset freshness verify before kernels_push (stale-dataset guard)
_INPUT_VERIFY_TIMEOUT = 60.0
_INPUT_VERIFY_INTERVAL = 3.0


def _api():
    """Lazy kaggle import; missing package → None (disabled, no crash).

    Auth is the kaggle package's own: authenticate() reads env directly
    (KAGGLE_API_TOKEN first, legacy KAGGLE_USERNAME/KAGGLE_KEY fallback)
    — config comes from the same process env, so nothing to wire here.
    """
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

# --- Plan K5: batch mode (kaggle_mode="batch") ---

def _get_storage():
    """Storage driver for staging uploads (seam: tests inject the moto driver)."""
    from app.services.storage import build_storage

    return build_storage()

def _norm_status(resp) -> str | None:
    """kaggle 2.2.4 status → lowercase (enum repr KernelWorkerStatus.COMPLETE
    → 'complete'). Mirrors deploy/kaggle/push.py _norm_status — server cannot
    import deploy scripts, so the small helper is replicated here."""
    value = resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None)
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name).lower()
    s = str(value)
    return s.rsplit(".", 1)[-1].strip().lower() if "." in s else s.strip().lower()

def adapt_batch_document(doc: dict) -> dict:
    """result.json (K4 notebook document shape) → ResultBody payload (spec §4,
    validated by schemas.ResultBody before ingest).

    Batch-grade ceilings: whole file → pages 1..N (preprocess ignored — caller
    logs the KAGGLE_MODE=loop hint); no dual-branch verdicts → verdict "ok" /
    page_flag "ok"; image blocks dropped (pixels never leave the kernel) as are
    empty-text blocks; table block text is already HTML, kept verbatim.
    gpu_seconds 0 — kernel log elapsed is wall time, not GPU seconds."""
    md_pages: list[str] = []
    pages_out: list[dict] = []
    for i, pg in enumerate(doc.get("pages") or [], 1):
        regions: list[dict] = []
        md_parts: list[str] = []
        for b in pg.get("blocks") or []:
            text = b.get("text") or ""
            if b.get("type") == "image" or not text.strip():
                continue
            regions.append({
                "id": str(b.get("id") or f"p{i}_b{len(regions)}"),
                "bbox": b.get("bbox"),
                "text": text,
                "verdict": "ok",
                "placeholder": False,
            })
            md_parts.append(_MD_PREFIX.get(b.get("type"), "") + text)
        page_md = "\n\n".join(md_parts)
        pages_out.append({
            "index": int(pg.get("page") or i),
            "width": int(pg.get("width") or 0),
            "height": int(pg.get("height") or 0),
            "page_flag": "ok",
            "markdown": page_md,
            "regions": regions,
        })
        md_pages.append(page_md)
    return {
        "model_version": BATCH_MODEL_VERSION,
        "gpu_seconds": 0.0,
        # kernel "problems" (precheck-gated / missing-OCR pages) → operator warnings
        "warnings": [str(p) for p in doc.get("problems") or []],
        "markdown": "\n\n---\n\n".join(md_pages),
        "edited_markdown": None,
        "pages": pages_out,
    }

def _api_dataset_exists(api, ref: str) -> bool:
    """Exists check via dataset_status when available (owner-scoped — works
    for PRIVATE datasets). dataset_list search does NOT return private
    datasets, so the search path reported "absent" for img2text-input every
    tick: delete skipped + create returned its silent "already in use" error
    payload → kernel pushed against the OLD input (bug: dataset stale).
    Search path kept as fallback for packages without dataset_status.
    Missing dataset (HTTPError 403/404 on .response) → False; other errors raise."""
    status_fn = getattr(api, "dataset_status", None)
    if status_fn is not None:
        try:
            status_fn(ref)
            return True
        except Exception as exc:
            if getattr(getattr(exc, "response", None), "status_code", None) in (403, 404):
                return False
            raise
    _owner, slug = ref.split("/", 1)
    list_fn = getattr(api, "dataset_list", None)
    with_resp_fn = getattr(api, "dataset_list_with_response", None)
    if list_fn is None and with_resp_fn is None:
        raise RuntimeError("kaggle package: dataset_list not found — cần kaggle>=1.6")
    if list_fn is not None:
        items = list_fn(search=slug)
    else:
        resp = with_resp_fn(search=slug)
        items = getattr(resp, "datasets", None)
    for item in items or []:
        if isinstance(item, dict):
            raw = str(item.get("ref") or "")
            item_owner = str(item.get("owner") or item.get("owner_ref") or "")
        else:
            raw = str(getattr(item, "ref", "") or "")
            item_owner = str(getattr(item, "owner_ref", "") or "")
        if not raw:
            continue
        if "/" not in raw:
            raw = f"{item_owner}/{raw}" if item_owner else raw
        if raw.casefold() == ref.casefold() or ("/" not in raw and raw.casefold() == slug.casefold()):
            return True
    return False

def _api_delete_dataset(api, ref: str) -> bool:
    """Delete ref; True = deleted (1.8-era returns None on success).
    Mirrors kcompat.api_delete_dataset — no delete API → False (caller errors)."""
    owner, slug = ref.split("/", 1)
    if hasattr(api, "dataset_delete"):
        return api.dataset_delete(owner, slug, no_confirm=True) is not False
    if hasattr(api, "datasets_delete"):
        return api.datasets_delete(ref) is not False
    return False

def _api_create_dataset(api, folder):
    """Upload-create from folder (dataset-metadata.json).
    Mirrors kcompat.api_create_dataset — kaggle 2.2.x renamed the API.
    kaggle 2.2.4 returns an error PAYLOAD instead of raising when the ref
    is still in use (title collision after an ineffective delete) — raise,
    so the spawn fails instead of silently pushing the old dataset."""
    if hasattr(api, "dataset_create_new"):
        result = api.dataset_create_new(str(folder))
    elif hasattr(api, "datasets_create_with_files"):
        result = api.datasets_create_with_files(upload_folder=str(folder))
    else:
        raise RuntimeError("kaggle package: dataset_create_new not found — cần kaggle>=1.6")
    if isinstance(result, dict):
        status, error = result.get("status"), result.get("error")
    else:
        status, error = getattr(result, "status", None), getattr(result, "error", None)
    if error or str(status or "").lower() == "error":
        raise RuntimeError(f"kaggle dataset create failed: {error or status}")
    return result


def _verify_input_dataset(api, ref: str, expected_name: str) -> None:
    """Stale-input guard: poll dataset_list_files until the STAGED upload is
    served (kaggle's create can return before the new files propagate).
    Timeout → RuntimeError: spawn skipped before kernels_push (the run would
    execute against the previous input), retried next tick."""
    deadline = time.monotonic() + _INPUT_VERIFY_TIMEOUT
    seen: list[str] = []
    last_error: Exception | None = None
    while True:
        try:
            resp = api.dataset_list_files(ref)
            files = getattr(resp, "dataset_files", None)
            if files is None:
                files = resp.get("files") if isinstance(resp, dict) else resp
            seen = []
            for f in files or []:
                if hasattr(f, "name"):
                    seen.append(str(f.name))
                elif isinstance(f, dict):
                    seen.append(str(f.get("name", "")))
            last_error = None
        except Exception as exc:  # not found / not propagated — keep polling
            last_error = exc
        if expected_name in seen:
            return
        if time.monotonic() >= deadline:
            detail = f" (last error: {last_error})" if last_error else ""
            raise RuntimeError(
                f"input dataset {ref} not refreshed: expected {expected_name!r}, "
                f"saw {seen} after {_INPUT_VERIFY_TIMEOUT:g}s — kernels_push "
                f"skipped, spawn retried next tick{detail}"
            )
        time.sleep(_INPUT_VERIFY_INTERVAL)

def _ensure_input_dataset(api, owner: str, folder: Path) -> None:
    """img2text-input: exists → DELETE + recreate with the staged folder
    (run_one.ensure_dataset refresh pattern — a version bump would serve the
    PREVIOUS input). Delete unavailable → raise, spawn skipped, retried next tick."""
    ref = f"{owner}/{INPUT_SLUG}"
    if _api_dataset_exists(api, ref) and not _api_delete_dataset(api, ref):
        raise RuntimeError(
            f"kaggle package has no dataset delete API — cannot replace {ref}"
        )
    _api_create_dataset(api, folder)

def _stage_batch_kernel(dest: Path) -> str:
    """Stage the batch script kernel from read-only templates: img2text_batch.py
    + kernel-batch-metadata.json (OWNER substituted; dataset_sources = the
    img2text-input dataset ONLY — the script carries all code). Returns the
    kernel ref (metadata id) the run is tracked under."""
    src = _stage_src()
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src / "kernel" / "img2text_batch.py", dest / "img2text_batch.py")
    meta = _sub_owner(
        json.loads(
            (src / "kernel" / "kernel-batch-metadata.json").read_text(encoding="utf-8")
        ),
        settings.kaggle_username,
    )
    meta["machine_shape"] = settings.kaggle_accelerator
    meta["accelerator"] = settings.kaggle_accelerator
    (dest / "kernel-metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return str(meta["id"])

async def _spawn_batch_run(api, session_factory, job: Job) -> bool:
    """queued job → stage input + dataset delete/create + kernels_push.

    Staging (input + kernel) lives in a fresh tmp dir, deleted after push —
    the run lives on Kaggle, not locally. Shared img2text-input slug means
    concurrent runs would overwrite each other's input: _ensure_batch_runs
    enforces a single-active-run guard before every spawn.

    True = job marked running + tracked in _batch_runs. False = the UPDATE
    matched 0 rows (an HTTP worker claimed the job mid-push): warning, no
    tracking — the caller must not start a second run this tick."""
    global _last_spawn
    owner = settings.kaggle_username
    data = await _get_storage().get(job.storage_key)
    build = Path(tempfile.mkdtemp(prefix="kaggle-img2text-batch-"))
    try:
        input_stage = build / "input"
        input_stage.mkdir()
        (input_stage / Path(job.storage_key).name).write_bytes(data)  # sha.<ext> keeps the ext
        (input_stage / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": f"{owner}/{INPUT_SLUG}",
                    "title": INPUT_SLUG,
                    "licenses": [{"name": "CC0-1.0"}],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        kernel_stage = build / "kernel"
        ref = _stage_batch_kernel(kernel_stage)
        # stale-input guard: refresh the dataset BEFORE push (the kernel
        # executes against the mounted dataset, never the staged folder),
        # then poll list_files until the staged upload is actually served —
        # pushing earlier runs against the PREVIOUS input (dataset stale)
        input_ref = f"{owner}/{INPUT_SLUG}"
        await asyncio.to_thread(_ensure_input_dataset, api, owner, input_stage)
        await asyncio.to_thread(
            _verify_input_dataset, api, input_ref, Path(job.storage_key).name
        )
        await asyncio.to_thread(api.kernels_push, str(kernel_stage))
        # D1: push OK → job visibly running (UI "Đang xử lý" instead of
        # "Chờ xử lý" for the whole run); lease = now + kaggle_timeout so
        # the reaper never requeues mid-run. started_at kept if already set.
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            result = await session.execute(
                update(Job)
                .where(Job.id == job.id, Job.status == "queued")
                .values(
                    status="running",
                    started_at=func.coalesce(Job.started_at, now),
                    lease_expires_at=now
                    + timedelta(seconds=settings.kaggle_timeout),
                )
            )
            await session.commit()
            claimed = result.rowcount == 0
        _last_spawn = time.monotonic()  # kernel pushed either way — gap applies
        if claimed:
            logger.warning(
                "kaggle batch: job %s claimed before running-mark "
                "(UPDATE rowcount 0) — run not tracked",
                job.id,
            )
            return False
        logger.info(
            "kaggle batch: job %s → running (lease +%ds)",
            job.id,
            settings.kaggle_timeout,
        )
    finally:
        shutil.rmtree(build, ignore_errors=True)
    _batch_runs[job.id] = {"ref": ref, "pushed_at": time.monotonic()}
    return True

async def _revert_job_queued(session_factory, job_id: int, why: str) -> None:
    """D1 failure path: kernel failed/error/timeout or ingest give-up →
    job back to queued with the lease cleared so the gap-guarded respawn
    picks it up next round (reaper must not also touch it).

    Rider guard: worker_token IS NULL — a running job claimed by an HTTP
    worker (claim raced the failure) is left alone, not clobbered."""
    async with session_factory() as session:
        result = await session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.worker_token.is_(None),
            )
            .values(status="queued", lease_expires_at=None)
        )
        await session.commit()
        reverted = result.rowcount > 0
    if not reverted:
        logger.warning(
            "kaggle batch: job %s revert skipped — claimed or not running "
            "(%s)",
            job_id, why,
        )
        return
    logger.info("kaggle batch: job %s reverted to queued (%s)", job_id, why)

async def _ingest_batch_result(api, session_factory, job_id: int, ref: str) -> None:
    """kernels_output → result.json → spec §4 ResultBody → job done."""
    out_dir = Path(tempfile.mkdtemp(prefix="kaggle-img2text-out-"))
    try:
        await asyncio.to_thread(
            api.kernels_output, ref, path=str(out_dir), quiet=False
        )
        doc = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            logger.warning("kaggle batch: job %s gone before ingest — drop", job_id)
            return
        if job.preprocess:
            logger.warning(
                "kaggle batch bỏ qua preprocess — dùng worker loop "
                "(KAGGLE_MODE=loop) khi cần"
            )
        body = ResultBody.model_validate(adapt_batch_document(doc))
        stored = await store_batch_result(
            session, job_id, body, now=datetime.now(timezone.utc),
            storage=_get_storage(),  # Plan D4: post-ingest auto output export
        )
        if not stored:
            logger.warning(
                "kaggle batch: job %s not ingestable (claimed or lease "
                "expired) — skip ingest",
                job_id,
            )
            return
    logger.info("kaggle batch: job %s done (%d pages)", job_id, len(body.pages))

async def _poll_batch_run(api, session_factory, job_id: int, run: dict) -> None:
    """One poll of a tracked run. complete → ingest (ref dropped only AFTER
    a successful pull+validate — a transient kernels_output/ValidationError
    failure retries next tick; _INGEST_MAX_FAILURES persistent failures drop
    the ref so a deterministic poison result can't loop forever);
    failed/error → drop ref + revert job to queued (respawn next tick,
    gap-guarded); ref older than kaggle_timeout → drop ref + revert +
    warning."""
    ref = str(run["ref"])
    status = _norm_status(await asyncio.to_thread(api.kernels_status, ref))
    if status == "complete":
        try:
            await _ingest_batch_result(api, session_factory, job_id, ref)
        except Exception:
            run["ingest_failures"] = run.get("ingest_failures", 0) + 1
            if run["ingest_failures"] >= _INGEST_MAX_FAILURES:
                _batch_runs.pop(job_id, None)
                logger.error(
                    "kaggle batch: ingest job %s failed %d times — ref dropped",
                    job_id, run["ingest_failures"], exc_info=True,
                )
                await _revert_job_queued(
                    session_factory, job_id, "ingest give-up"
                )
            else:
                logger.warning(
                    "kaggle batch: ingest job %s failed — retry next tick",
                    job_id, exc_info=True,
                )
            return
        _batch_runs.pop(job_id, None)  # success only — retry pull on failure
        return
    if status in _FAILED_STATUSES:
        _batch_runs.pop(job_id, None)
        logger.warning(
            "kaggle batch: kernel %s %s — ref dropped, job %s stays queued "
            "(respawn next tick after gap)",
            ref, status, job_id,
        )
        await _revert_job_queued(session_factory, job_id, f"kernel {status}")
        return
    if time.monotonic() - run["pushed_at"] > settings.kaggle_timeout:
        _batch_runs.pop(job_id, None)
        logger.warning(
            "kaggle batch: ref %s older than kaggle_timeout=%ds — ref dropped, "
            "job %s stays queued",
            ref, settings.kaggle_timeout, job_id,
        )
        await _revert_job_queued(session_factory, job_id, "kaggle_timeout")

async def _ensure_batch_runs(api, session_factory) -> bool:
    """Plan K5 batch tick: poll every tracked run, then spawn at most 1 new
    run. True = spawned.

    Single-active-run guard: the img2text-input slug is shared, so no new
    spawn while ANY run is tracked (a 320s run + queue wait can exceed the
    600s gap — gap alone doesn't prevent overlap). Poison-job guard: a spawn
    failure logs + moves to the NEXT queued candidate this tick instead of
    head-of-line blocking the queue. Never raises (ensure_worker caller)."""
    global _last_spawn
    for job_id, run in list(_batch_runs.items()):
        await _poll_batch_run(api, session_factory, job_id, run)
    if _batch_runs:  # active run(s) — shared input slug: never overlap
        return False
    now = time.monotonic()
    min_gap = await get_runtime_setting(
        session_factory, "kaggle_min_gap_seconds", settings.kaggle_min_gap_seconds
    )
    if now - _last_spawn < min_gap:
        logger.info(
            "kaggle batch: last spawn %.0fs ago < gap %ds — skip",
            now - _last_spawn,
            min_gap,
        )
        return False
    async with session_factory() as session:
        queued = (
            await session.execute(
                select(Job).where(Job.status == "queued").order_by(Job.id)
            )
        ).scalars().all()
    for job in (j for j in queued if j.id not in _batch_runs):
        try:
            tracked = await _spawn_batch_run(api, session_factory, job)
        except Exception:
            _last_spawn = time.monotonic()  # anti-hammer on persistent errors
            logger.warning(
                "batch spawn failed job=%s", job.id, exc_info=True
            )
            continue  # next candidate — a poison job must not block the queue
        if not tracked:
            # claimed mid-push: the pushed kernel still runs — never start
            # a second one this tick (shared img2text-input slug)
            return False
        logger.info(
            "kaggle batch: pushed job %s → kernel %s",
            job.id, _batch_runs[job.id]["ref"],
        )
        return True
    return False


async def ensure_worker(session_factory) -> bool:
    """Spawn a Kaggle kernel run when the queue needs it. True = pushed.

    Never raises: orchestration failures log a warning and return False
    (a broken Kaggle pass must not kill the scheduler job)."""
    global _last_spawn
    if not settings.kaggle_enabled:
        return False
    try:
        api = _api()  # inside try: constructor/auth errors must also return False (never-raise contract)
        if api is None:
            return False
        mode = await get_runtime_setting(
            session_factory, "kaggle_mode", settings.kaggle_mode
        )
        if mode != "loop":
            # Plan K5 default (batch): drive the standalone script kernel per job
            return await _ensure_batch_runs(api, session_factory)
        ref = settings.kaggle_kernel_ref.strip()
        resp = await asyncio.to_thread(api.kernels_status, ref)
        status = (
            resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None)
        )
        if str(status).lower() in _ACTIVE_STATUSES:
            logger.info("kaggle: kernel %s active (%s) — skip", ref, status)
            return False
        queued = await _count_queued(session_factory)
        min_queue = await get_runtime_setting(
            session_factory, "kaggle_min_queue", settings.kaggle_min_queue
        )
        if queued < min_queue:
            logger.info(
                "kaggle: queued=%d < min_queue=%d — skip",
                queued,
                min_queue,
            )
            return False
        now = time.monotonic()
        min_gap = await get_runtime_setting(
            session_factory, "kaggle_min_gap_seconds", settings.kaggle_min_gap_seconds
        )
        if now - _last_spawn < min_gap:
            logger.info(
                "kaggle: last spawn %.0fs ago < gap %ds — skip",
                now - _last_spawn,
                min_gap,
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
