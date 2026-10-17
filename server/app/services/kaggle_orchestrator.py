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
status, pulls the per-job outputs ({job_id}_result.json) and ingests them
into the jobs (partial-fail per job). No public URL needed.
Runs live in the in-memory _batch_runs map; the kernel ref is ALSO persisted
in jobs.kaggle_ref (spec 2026-10-09) so _ensure_batch_runs re-adopts an
"extracting" job after a restart — the poll loop resumes, no orphan kernel.
"""

import asyncio
import json
import logging
import secrets
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.models import Job, WorkerHeartbeat, WorkerSession
from app.core.schemas import IMAGE_MARKER, ResultBody
from app.core.security import hash_worker_token
from app.services.job_results import store_batch_result
from app.services.kaggle_quota import quota_remaining_seconds
from app.services.runtime_settings import get_runtime_setting

logger = logging.getLogger(__name__)

# Spec session worker T4/T6 seam: claim response server_flags.quota_low —
# _ensure_sessions tick set khi quota API dưới ngưỡng (AC5/AC6); default
# False. ponytail: in-process flag — cùng single-worker assumption với
# _last_spawn.
_quota_low = False

def session_quota_low() -> bool:
    return _quota_low

DATASET_SLUG = "img2text-worker-files"
INPUT_SLUG = "img2text-input"  # batch input dataset (run_one.py K4, shared slug)
# F3 (spec 2026-10-10): manifest input_url presigned GET window — kernel
# downloads right after the spawn tick. P2 #19: 3600 → settings.input_url_expires
# (default 900s/15 phút) — fetch ngay nên window ngắn, giảm URL exposure.
# kernel statuses meaning "run in progress" (case-insensitive match)
_ACTIVE_STATUSES = frozenset({"running", "pending", "queued"})
# batch statuses meaning "terminal" (normalized lowercase). P2: literal
# kernel status "timeout" is terminal too (spec: timeout → failed+extracting,
# replaces the revert-and-respawn of 2263d24).
_FAILED_STATUSES = frozenset({"failed", "error", "cancelled", "timeout"})
# mirrors kernel VL_MODEL / worker build_result default (result.json has no version)
BATCH_MODEL_VERSION = "PaddleOCR-VL-1.5-0.9B"
# per-block markdown prefixes (batch doc_title → H1, paragraph_title → H2;
# table/text → raw — block.text is already HTML for tables)
_MD_PREFIX = {"doc_title": "# ", "paragraph_title": "## "}
# mirror deploy/kaggle/files/pipeline.py _MARKER — server cannot import deploy
# scripts; marker chữ nằm ở app.core.schemas.IMAGE_MARKER (dùng chung exports/render)

# --- wave-3 (spec 2026-10-13) — mirror helpers từ kernel img2text_batch.py
# (server KHÔNG import deploy scripts — copy nhỏ, test contract pin parity).

def _band_tol(h1: float, h2: float) -> float:
    return max(10.0, 0.3 * max(h1, h2))

def _linearize_blocks(blocks: list[dict]) -> list[dict]:
    """Reading order: y-bands theo center y (tolerance max(10, h*0.3)) → mỗi
    band sort x0 trái→phải → flatten (2 cột cùng hàng: trái trước)."""
    keyed = []
    for i, b in enumerate(blocks):
        bbox = b.get("bbox")
        if bbox and len(bbox) == 4:
            cy, h, x0 = (bbox[1] + bbox[3]) / 2, abs(bbox[3] - bbox[1]), bbox[0]
        else:
            cy, h, x0 = float("inf"), 0.0, float("inf")
        keyed.append((cy, h, x0, i, b))
    keyed.sort(key=lambda t: (t[0], t[3]))
    bands: list[list[tuple]] = []
    for t in keyed:
        if (bands and t[0] != float("inf")
                and t[0] - bands[-1][-1][0] <= _band_tol(t[1], bands[-1][-1][1])):
            bands[-1].append(t)
        else:
            bands.append([t])
    return [b for band in bands for _, _, _, _, b in sorted(band, key=lambda t: (t[2], t[3]))]

def _cells_md(cells: list[list[dict]]) -> str:
    """cells (kernel parse) → GFM pipe — mirror kernel _table_cells_to_md:
    header = hàng có th (hoặc hàng đầu); colspan → lặp; rowspan → bỏ."""
    if not cells:
        return ""
    h = next((i for i, r in enumerate(cells) if any(c.get("header") for c in r)), 0)
    def texts(row):
        out = []
        for c in row:
            out.extend([str(c.get("text") or "")] * max(1, int(c.get("colspan") or 1)))
        return out
    def fmt(row):
        return "| " + " | ".join(t.replace("|", "\\|") for t in texts(row)) + " |"
    head = texts(cells[h])
    lines = [fmt(cells[h]), "| " + " | ".join(["---"] * len(head)) + " |"]
    lines += [fmt(r) for i, r in enumerate(cells) if i != h]
    return "\n".join(lines)

# 0.0 = never spawned; gap check BỎ qua khi falsy — monotonic baseline là
# boot time, VM mới boot (< min_gap) sẽ luôn "skip" nếu treat 0.0 là mốc.
_last_spawn = 0.0
# ceiling: persistent ingest failures for one ref → drop instead of looping
_INGEST_MAX_FAILURES = 3
# Plan K5 batch runs keyed by the KERNEL REF (run-level):
#   {ref: {"ref", "pushed_at", "job_ids", "ingest_failures"}}.
# ref = owner/img2text-batch (constant per deployment), so one map entry ==
# the ONE live run (single-active-run guard); jobs sharing kaggle_ref share
# the entry. In-memory hot index; jobs.kaggle_ref is the durable copy — a
# restart re-adopts extracting jobs GROUPED BY ref each tick (see
# _ensure_batch_runs).
_batch_runs: dict[str, dict] = {}
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

async def _touch_batch_heartbeat(
    session_factory, current_job_id: int | None = None,
    worker_id: str = "kaggle-batch",
) -> None:
    """wave-2 #7: orchestrator marker — upsert row worker_id=kind (batch:
    "kaggle-batch"; session worker T6: "kaggle-session") khi spawn + mỗi poll
    status. Telemetry only: lỗi DB không được phá spawn/poll (warning + bỏ qua)."""
    try:
        async with session_factory() as session:
            now = datetime.now(timezone.utc)
            await session.execute(
                pg_insert(WorkerHeartbeat)
                .values(
                    worker_id=worker_id, kind=worker_id,
                    last_seen=now, current_job_id=current_job_id,
                )
                .on_conflict_do_update(
                    index_elements=[WorkerHeartbeat.worker_id],
                    set_={"kind": worker_id, "last_seen": now,
                          "current_job_id": current_job_id},
                )
            )
            await session.commit()
    except Exception:
        logger.warning("kaggle %s: heartbeat upsert lỗi", worker_id, exc_info=True)

# --- Plan K5: batch mode (kaggle_mode="batch") ---

# --- Spec session worker (2026-10-16 T6): mode "session" ---
# 1 kernel session active duy nhất; live index {session_id: {id, ref,
# spawned_at}} — DB worker_sessions là bản durable (restart adopt).
_sessions: dict[int, dict] = {}

async def _spawn_session(
    api, session_factory, *, key: str | None = None
) -> bool:
    """Stage + push session kernel (AC3): key random → script chèn lúc push
    (__SESSION_KEY__); kernel-metadata KHÔNG chứa key; DB upsert hash-at-rest.
    Claim đầu tiên sẽ gán job.session_id qua next_job (T4) — KHÔNG update
    extracting ở spawn (khác batch path)."""
    global _last_spawn
    owner = settings.kaggle_username
    key = key or secrets.token_urlsafe(32)
    key_hash = hash_worker_token(key)
    src = _stage_src()
    build = Path(tempfile.mkdtemp(prefix="kaggle-img2text-session-"))
    try:
        for name in ("img2text_session.py", "img2text_batch.py"):
            shutil.copyfile(src / "kernel" / name, build / name)
        script_path = build / "img2text_session.py"
        api_base = (settings.worker_base_url or "").strip() or settings.base_url
        script_path.write_text(
            script_path.read_text(encoding="utf-8")
            .replace("__SESSION_KEY__", key)
            .replace("__BASE_URL__", api_base),
            encoding="utf-8",
        )
        if (
            not api_base
            or "localhost" in api_base
            or "127.0.0.1" in api_base
        ):
            logger.warning(
                "kaggle session: api_base %r không reach được từ Kaggle kernel",
                api_base,
            )
        meta = _sub_owner(
            json.loads(
                (src / "kernel" / "kernel-session-metadata.json").read_text(
                    encoding="utf-8"
                )
            ),
            owner,
        )
        meta["machine_shape"] = settings.kaggle_accelerator
        meta["accelerator"] = settings.kaggle_accelerator
        (build / "kernel-metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        ref = await asyncio.to_thread(api.kernels_push, str(build))
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            row = WorkerSession(kernel_ref=str(ref), key_hash=key_hash)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            session_id = row.id
    finally:
        shutil.rmtree(build, ignore_errors=True)
    _last_spawn = time.monotonic()
    _sessions[session_id] = {
        "id": session_id,
        "ref": str(ref),
        "spawned_at": now,
    }
    await _touch_batch_heartbeat(session_factory, worker_id="kaggle-session")
    logger.info("kaggle session: pushed kernel %s (session %s)", ref, session_id)
    return True

async def _close_session(session_factory, session_id: int) -> list[int]:
    """AC3/AC9: DELETE worker_sessions row NGAY (hash mất). Null
    jobs.session_id TƯỜNG MINH trước delete (AC3a: job không mất) — không
    dựa FK ON DELETE SET NULL: _cleanup_dead_session gọi sau đó
    _revert_job_queued/_fail_job_extracting có guard session_id IS NULL, FK
    tắt → job treo. Trả về các job extracting của session (đã thu trước khi
    delete) để caller revert/fail."""
    _sessions.pop(session_id, None)
    async with session_factory() as session:
        claimed = (
            await session.execute(
                select(Job.id).where(
                    Job.status == "extracting",
                    Job.session_id == session_id,
                )
            )
        ).scalars().all()
        # AC3a: null tường minh (FK chỉ là lưới an toàn).
        await session.execute(
            update(Job).where(Job.session_id == session_id).values(session_id=None)
        )
        # DELETE NGAY (AC3/AC9: hash-at-rest không sống sót sau close).
        await session.execute(
            delete(WorkerSession).where(WorkerSession.id == session_id)
        )
        await session.commit()
    logger.info(
        "kaggle session: closed session %s (claimed jobs %s)",
        session_id, list(claimed),
    )
    return list(claimed)

async def _poll_session(api, session_factory, entry: dict) -> str:
    """One poll (AC9): active → 'active'; complete → graceful 'closed';
    failed/error/cancelled/timeout → 'failed' (AC10 caller fail jobs);
    age > kaggle_session_max_age_s → 'expired' (caller revert + respawn)."""
    session_id = entry["id"]
    await _touch_batch_heartbeat(
        session_factory, worker_id="kaggle-session"
    )
    status = _norm_status(await asyncio.to_thread(api.kernels_status, entry["ref"]))
    age_s = (
        datetime.now(timezone.utc) - entry["spawned_at"]
    ).total_seconds()
    if age_s > settings.kaggle_session_max_age_s:
        logger.warning(
            "kaggle session %s older than max_age=%ds — close + respawn",
            session_id, settings.kaggle_session_max_age_s,
        )
        return "expired"
    if status in _ACTIVE_STATUSES:
        return "active"
    if status in _FAILED_STATUSES:
        return "failed"
    return "closed"  # complete (graceful — queue đã rỗng lúc exit)

async def _ensure_sessions(api, session_factory) -> bool:
    """Session tick (AC1/AC5/AC6/AC9): adopt DB live sessions sau restart →
    poll từng session → close/revert/fail dọn dẹp → quota gate → spawn 1
    session mới khi queue cần. True = spawned."""
    global _last_spawn
    tracked = list(_sessions.values())  # poll snapshot (adopt không re-poll)
    # adopt (AC9): DB live sessions chưa có trong map (restart / spawn crash)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(WorkerSession).where(WorkerSession.closed_at.is_(None))
            )
        ).scalars().all()
    for row in rows:
        if row.id in _sessions:
            continue
        entry = {
            "id": row.id,
            "ref": row.kernel_ref,
            "spawned_at": row.spawned_at,
        }
        outcome = await _poll_session(api, session_factory, entry)
        if outcome == "active":
            _sessions[row.id] = entry
            logger.info(
                "kaggle session: adopt session %s ref %s (restart recovery)",
                row.id, row.kernel_ref,
            )
        else:
            await _cleanup_dead_session(
                session_factory, row.id, fail_jobs=(outcome == "failed"),
                why=f"restart poll {outcome}",
            )
    for entry in tracked:
        outcome = await _poll_session(api, session_factory, entry)
        if outcome == "active":
            continue
        await _cleanup_dead_session(
            session_factory, entry["id"],
            fail_jobs=(outcome == "failed"), why=outcome,
        )
    if _sessions:  # 1 session active tuyệt đối (shared input slug rationale)
        return False
    queued = await _count_queued(session_factory)
    min_queue = await get_runtime_setting(
        session_factory, "kaggle_min_queue", settings.kaggle_min_queue
    )
    if queued < min_queue:
        return False
    now = time.monotonic()
    min_gap = await get_runtime_setting(
        session_factory, "kaggle_min_gap_seconds", settings.kaggle_min_gap_seconds
    )
    if _last_spawn and now - _last_spawn < min_gap:
        logger.info(
            "kaggle session: last spawn %.0fs ago < gap %ds — skip",
            now - _last_spawn, min_gap,
        )
        return False
    # AC6: quota gate trước dispatch — dưới ngưỡng → không spawn + flag
    # quota_low (claim response báo worker exit 0, AC5).
    global _quota_low
    min_quota = await get_runtime_setting(
        session_factory, "kaggle_session_min_quota_s",
        settings.kaggle_session_min_quota_s,
    )
    remaining = await asyncio.to_thread(quota_remaining_seconds, api)
    _quota_low = remaining is None or remaining < min_quota
    if _quota_low:
        logger.warning(
            "kaggle session: quota còn %s < %ds — skip spawn (quota_low)",
            f"{remaining:.0f}s" if remaining is not None else "?", min_quota,
        )
        return False
    try:
        return await _spawn_session(api, session_factory)
    except Exception:
        _last_spawn = time.monotonic()  # anti-hammer on persistent errors
        logger.warning("kaggle session: spawn failed", exc_info=True)
        return False

async def _cleanup_dead_session(
    session_factory, session_id: int, *, fail_jobs: bool, why: str
) -> None:
    """Kernel dead (AC10) → fail từng job extracting; graceful/expired →
    revert về queued. Cả 2: session row xóa (FK nulls session_id) — không
    để job treo trỏ session đã xóa (AC3b)."""
    claimed = await _close_session(session_factory, session_id)
    for job_id in claimed:
        if fail_jobs:
            await _fail_job_extracting(
                session_factory, job_id, f"Kaggle session {why}"
            )
        else:
            await _revert_job_queued(session_factory, job_id, why)

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

    Batch-grade ceilings: whole file → pages 1..N (preprocess propagate qua
    manifest per job — kernel batch áp dụng page-select/rotate trước OCR,
    wave-2 #4); no dual-branch verdicts → verdict "ok" /
    page_flag "ok"; image blocks KEPT as verdict image_unextractable + marker
    (crop flow downstream — pixels never leave the kernel, only bbox);
    empty-text non-image blocks dropped. wave-3: blocks linearized theo
    reading order (y-band, 2 cột cùng hàng trái trước); table block có cells
    → md GFM pipe (html+cells passthrough vào region jsonb); image marker cùng
    hàng → 1 dòng cách space."""
    md_pages: list[str] = []
    pages_out: list[dict] = []
    for i, pg in enumerate(doc.get("pages") or [], 1):
        regions: list[dict] = []
        md_parts: list[str] = []
        last_marker: tuple | None = None  # (center_y, height) marker vừa emit
        for b in _linearize_blocks(pg.get("blocks") or []):
            text = b.get("text") or ""
            is_image = b.get("type") == "image"
            if not is_image and not text.strip():
                continue  # truly-empty non-image block is meaningless
            rid = str(b.get("id") or f"p{i}_b{len(regions)}")
            region = {
                "id": rid,
                "bbox": b.get("bbox"),
                "text": text,
                "verdict": "image_unextractable" if is_image else "ok",
                "placeholder": is_image,
            }
            if b.get("html"):
                region["html"] = b["html"]
            if b.get("cells"):
                region["cells"] = b["cells"]
            regions.append(region)
            pos = None
            if is_image:
                # same marker as deploy/kaggle pipeline.py → exports.py
                # _materialize_crops rewrites it into the cached crop
                piece = IMAGE_MARKER.format(region_id=rid)
                bbox = b.get("bbox")
                if bbox and len(bbox) == 4:
                    pos = ((bbox[1] + bbox[3]) / 2, abs(bbox[3] - bbox[1]))
            elif b.get("cells"):
                piece = _cells_md(b["cells"])
            else:
                piece = _MD_PREFIX.get(b.get("type"), "") + text
            if not piece:
                continue
            if (md_parts and last_marker is not None and pos is not None
                    and abs(pos[0] - last_marker[0]) <= _band_tol(pos[1], last_marker[1])):
                md_parts[-1] += " " + piece  # 2 marker/image cùng hàng → CÙNG dòng
            else:
                md_parts.append(piece)
            last_marker = pos
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


def _verify_input_dataset(api, ref: str, expected_names: list[str]) -> None:
    """Stale-input guard: poll dataset_list_files until EVERY staged upload of
    the batch is served (kaggle's create can return before the new files
    propagate). Timeout → RuntimeError: spawn skipped before kernels_push
    (the run would execute against the previous input), retried next tick."""
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
        missing = [n for n in expected_names if n not in seen]
        if not missing:
            return
        if time.monotonic() >= deadline:
            detail = f" (last error: {last_error})" if last_error else ""
            raise RuntimeError(
                f"input dataset {ref} not refreshed: missing {missing}, "
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
    img2text-input dataset + the img2text-wheelbuild-env wheelhouse — the
    script carries all code, the wheelhouse feeds its --no-index venv
    install). Returns the
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

class _DatasetSpawnError(Exception):
    """Dataset-wide spawn failure (kernel staging / dataset refresh /
    verify / push) — NOT job-specific. _ensure_batch_runs aborts the whole
    tick instead of dropping candidates: retrying a smaller batch would just
    repeat the full verify timeout for no reason."""

async def _spawn_batch_run(api, session_factory, jobs: list[Job]) -> bool:
    """queued jobs → stage {job_id}__{name} for each + dataset delete/create
    (ALL staged files verified) + kernels_push + ONE transaction marking every
    job extracting with the same ref.

    Staging (input + kernel) lives in a fresh tmp dir, deleted after push —
    the run lives on Kaggle, not locally. Shared img2text-input slug means
    concurrent runs would overwrite each other's input: _ensure_batch_runs
    enforces a single-active-run guard before every spawn.

    Raises: the per-job storage read fails → plain exception (job-specific
    poison — the caller drops that head candidate and retries the rest);
    everything after it → _DatasetSpawnError (dataset-wide, abort the tick).

    True = ≥1 job marked extracting + run tracked in _batch_runs. False =
    every UPDATE matched 0 rows (HTTP workers claimed the batch mid-push):
    warning, no tracking — the caller must not start a second run this tick.
    A PARTIAL claim tracks only the jobs WE marked (the rest stay with their
    claimer; no orphan extracting rows)."""
    global _last_spawn
    owner = settings.kaggle_username
    # per-job poison FIRST: a MISSING upload aborts before any Kaggle call
    # (head-check only — F3 never reads the bytes).
    storage = _get_storage()
    for job in jobs:
        if not await storage.exists(job.storage_key):
            raise KeyError(job.storage_key)
    build = Path(tempfile.mkdtemp(prefix="kaggle-img2text-batch-"))
    try:
        input_stage = build / "input"
        input_stage.mkdir()
        # F3: stage manifest.json ONLY (vài byte) — the kernel downloads each
        # file from the presigned GET url and verifies sha256; KHÔNG copy file
        # lớn vào dataset. filename keeps the {job_id}__{orig} prefix contract
        # (mount fallback + unambiguous reverse mapping).
        manifest = {
            "jobs": [
                {
                    "job_id": job.id,
                    "input_url": await storage.presign_get(
                        job.storage_key, settings.input_url_expires
                    ),
                    "filename": f"{job.id}__{Path(job.storage_key).name}",
                    # content-addressed key uploads/{sha256}.{ext} → the hash
                    "sha256": Path(job.storage_key).stem,
                    # P2-6: preprocess propagate → manifest → kernel batch
                    # đọc + áp dụng trước OCR (wave-2 #4; extra key không
                    # phá contract: entries khác giữ nguyên)
                    "preprocess": (
                        json.loads(job.preprocess) if job.preprocess else None
                    ),
                }
                for job in jobs
            ]
        }
        (input_stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        expected: list[str] = ["manifest.json"]
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
        try:
            ref = _stage_batch_kernel(kernel_stage)
            # stale-input guard: refresh the dataset BEFORE push (the kernel
            # executes against the mounted dataset, never the staged folder),
            # then poll list_files until the WHOLE batch is actually served —
            # pushing earlier runs against the PREVIOUS input (dataset stale)
            input_ref = f"{owner}/{INPUT_SLUG}"
            await asyncio.to_thread(_ensure_input_dataset, api, owner, input_stage)
            await asyncio.to_thread(
                _verify_input_dataset, api, input_ref, expected
            )
            await asyncio.to_thread(api.kernels_push, str(kernel_stage))
        except Exception as exc:
            raise _DatasetSpawnError(str(exc)) from exc
        # D1: push OK → the batch enters the "extracting" phase with the
        # kernel ref persisted (kaggle_ref = restart adoption; UI shows the
        # phase for the whole run); lease = now + kaggle_timeout so the reaper
        # never requeues mid-run. started_at kept if already set.
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            marked: list[int] = []
            for job in jobs:
                result = await session.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.status == "queued")
                    .values(
                        status="extracting",
                        kaggle_ref=ref,
                        started_at=func.coalesce(Job.started_at, now),
                        lease_expires_at=now
                        + timedelta(seconds=settings.kaggle_timeout),
                    )
                )
                if result.rowcount:
                    marked.append(job.id)
            await session.commit()
        _last_spawn = time.monotonic()  # kernel pushed either way — gap applies
        if not marked:
            logger.warning(
                "kaggle batch: jobs %s claimed before extracting-mark "
                "(UPDATE rowcount 0) — run not tracked",
                [j.id for j in jobs],
            )
            return False
        if len(marked) < len(jobs):
            logger.warning(
                "kaggle batch: jobs %s claimed mid-spawn — run tracks only %s",
                [j.id for j in jobs if j.id not in set(marked)], marked,
            )
        logger.info(
            "kaggle batch: jobs %s → extracting (lease +%ds, ref %s)",
            marked, settings.kaggle_timeout, ref,
        )
    finally:
        shutil.rmtree(build, ignore_errors=True)
    # map was empty here (single-active-run guard) — one entry per run
    _batch_runs[ref] = {
        "ref": ref,
        "pushed_at": time.monotonic(),
        "job_ids": marked,
        "ingest_failures": 0,
    }
    # wave-2 #7: spawn → mark worker kaggle-batch sống (admin card)
    await _touch_batch_heartbeat(session_factory, marked[0] if marked else None)
    return True

async def _revert_job_queued(session_factory, job_id: int, why: str) -> None:
    """D1 failure path: kernel timeout or ingest give-up → job back to
    queued with the lease cleared so the gap-guarded respawn picks it up
    next round (reaper must not also touch it).

    Rider guards: worker_token_hash IS NULL (HTTP worker claim không bị
    clobber) + session_id IS NULL (session worker claim — spec T4)."""
    async with session_factory() as session:
        result = await session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "extracting",
                Job.worker_token_hash.is_(None),
                Job.session_id.is_(None),
            )
            .values(status="queued", lease_expires_at=None)
        )
        await session.commit()
        reverted = result.rowcount > 0
    if not reverted:
        logger.warning(
            "kaggle: job %s revert skipped — claimed or not extracting (%s)",
            job_id, why,
        )
        return
    logger.info("kaggle: job %s reverted to queued (%s)", job_id, why)

async def _ingest_batch_result(session_factory, job_id: int, out_dir: Path) -> None:
    """{job_id}_result.json (the run's pulled output dir) → spec §4
    ResultBody → store. FileNotFoundError / JSONDecodeError / ValidationError
    bubble up = THIS job's output unusable (partial-fail: only this job gets
    failed by the caller); anything else (DB/storage) = run-level transient."""
    doc = json.loads(
        (out_dir / f"{job_id}_result.json").read_text(encoding="utf-8")
    )
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            logger.warning("kaggle batch: job %s gone before ingest — drop", job_id)
            return
        if job.status == "cancelled":
            # Owner-cancelled (POST /api/jobs/{id}/cancel) — terminal, no
            # ingest, no fail-mark, no requeue.
            logger.info("kaggle batch: job %s cancelled — skip ingest", job_id)
            return
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

async def _ingest_batch_crops(job_id: int, out_dir: Path) -> None:
    """WS-PIPE task 3: {job_id}_crop_{rid}.png (kernel output) →
    storage.put exports/{job_id}/crops/{rid}.png. Optional artifact: 1 crop
    lỗi (storage/không đọc được) chỉ log + bỏ crop đó — không bao giờ fail job."""
    storage = _get_storage()
    prefix = f"{job_id}_crop_"
    for f in sorted(out_dir.glob(f"{job_id}_crop_*.png")):
        rid = f.stem[len(prefix):]
        key = f"exports/{job_id}/crops/{rid}.png"
        try:
            await storage.put(key, f.read_bytes())
        except Exception:
            logger.warning(
                "kaggle batch: crop %s ingest fail (bỏ, job không ảnh hưởng)",
                key, exc_info=True,
            )

async def _ingest_complete_run(api, session_factory, run: dict) -> None:
    """kernel complete → ONE kernels_output pull → each job ingests its OWN
    {job_id}_result.json (N files, no overwrite). Partial-fail policy: a job
    whose output is missing/unparsable is failed at step "extracting" HERE
    (specific error) — the other jobs still ingest in the same tick.
    Raise = run-level transient (pull / DB / storage) → the caller retries
    the whole run next tick (ref kept)."""
    ref = str(run["ref"])
    out_dir = Path(tempfile.mkdtemp(prefix="kaggle-img2text-out-"))
    try:
        await asyncio.to_thread(
            api.kernels_output, ref, path=str(out_dir), quiet=False
        )
        for job_id in run["job_ids"]:
            try:
                await _ingest_batch_result(session_factory, job_id, out_dir)
            except FileNotFoundError:
                error = f"Kaggle kernel thiếu output {job_id}_result.json"
                logger.warning(
                    "kaggle batch: %s — job %s failed at step extracting",
                    error, job_id,
                )
                await _fail_job_extracting(session_factory, job_id, error)
            except (json.JSONDecodeError, ValidationError) as exc:
                error = f"Kaggle kernel output {job_id}_result.json không hợp lệ"
                logger.warning(
                    "kaggle batch: %s (%s) — job %s failed at step extracting",
                    error, exc, job_id,
                )
                await _fail_job_extracting(session_factory, job_id, error)
            else:
                # crops SAU result OK — result fail → không put (tránh mồ côi)
                await _ingest_batch_crops(job_id, out_dir)  # optional, partial-fail
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

async def _fail_job_extracting(session_factory, job_id: int, error: str) -> None:
    """job → failed at step "extracting" with the given error (spec
    2026-10-09: terminal kernel failure / unusable output — the owner
    retries explicitly via POST /api/jobs/{id}/retry; no silent respawn).
    Rider guard kept: a worker-claimed job (HTTP hoặc session) is not
    clobbered."""
    async with session_factory() as session:
        result = await session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "extracting",
                Job.worker_token_hash.is_(None),
                Job.session_id.is_(None),
            )
            .values(
                status="failed",
                failed_step="extracting",
                # P2: the owner sees WHY — error names the kernel status
                error=error,
                finished_at=datetime.now(timezone.utc),
                lease_expires_at=None,
                # wave-5 S1 refund: failed → hoàn bytes
                upload_bytes=0,
            )
        )
        await session.commit()
        if result.rowcount == 0:
            logger.warning(
                "kaggle batch: fail mark skipped job %s — claimed or not "
                "extracting",
                job_id,
            )

async def _poll_batch_run(api, session_factory, run: dict) -> None:
    """One poll of a tracked run (ref-keyed; run["job_ids"] = the batch).
    complete → ONE pull + per-job ingest (ref dropped only AFTER every job
    was attempted — a transient pull/DB failure retries the run next tick;
    a job with missing/unparsable output fails THAT job only, partial-fail;
    _INGEST_MAX_FAILURES persistent run-level failures drop the ref +
    revert ALL jobs still extracting so a poison pull can't loop forever);
    failed/error/cancelled/timeout → drop ref + fail EVERY job at step
    "extracting" (owner retries via POST /retry; job.error names the kernel
    status); run older than kaggle_timeout → drop ref + revert ALL jobs to
    queued + warning."""
    ref = str(run["ref"])
    job_ids: list[int] = list(run["job_ids"])
    # wave-2 #7: mỗi poll status → refresh last_seen của marker kaggle-batch
    await _touch_batch_heartbeat(session_factory, job_ids[0] if job_ids else None)
    status = _norm_status(await asyncio.to_thread(api.kernels_status, ref))
    if status == "complete":
        try:
            await _ingest_complete_run(api, session_factory, run)
        except Exception:
            run["ingest_failures"] = run.get("ingest_failures", 0) + 1
            if run["ingest_failures"] >= _INGEST_MAX_FAILURES:
                _batch_runs.pop(ref, None)
                logger.error(
                    "kaggle batch: ingest ref %s failed %d times — ref dropped",
                    ref, run["ingest_failures"], exc_info=True,
                )
                for job_id in job_ids:
                    await _revert_job_queued(
                        session_factory, job_id, "ingest give-up"
                    )
            else:
                logger.warning(
                    "kaggle batch: ingest ref %s failed — retry next tick",
                    ref, exc_info=True,
                )
            return
        _batch_runs.pop(ref, None)  # every job attempted — retry pull on failure
        return
    if status in _FAILED_STATUSES:
        _batch_runs.pop(ref, None)
        logger.warning(
            "kaggle batch: kernel %s %s — ref dropped, jobs %s failed at step "
            "extracting (retry via POST /api/jobs/<id>/retry)",
            ref, status, job_ids,
        )
        # spec 2026-10-09: terminal kernel failure fails the job at step
        # "extracting" (supersedes the revert-and-respawn of 2263d24 —
        # the owner retries explicitly).
        for job_id in job_ids:
            await _fail_job_extracting(
                session_factory, job_id, f"Kaggle kernel {status}"
            )
        return
    if time.monotonic() - run["pushed_at"] > settings.kaggle_timeout:
        _batch_runs.pop(ref, None)
        logger.warning(
            "kaggle batch: ref %s older than kaggle_timeout=%ds — ref dropped, "
            "jobs %s stay queued",
            ref, settings.kaggle_timeout, job_ids,
        )
        for job_id in job_ids:
            await _revert_job_queued(session_factory, job_id, "kaggle_timeout")

async def _ensure_batch_runs(api, session_factory) -> bool:
    """Plan K5 batch tick: poll every tracked run, then spawn ONE new run
    staging ALL queued jobs up to kaggle_batch_max_jobs. True = spawned.

    Single-active-run guard: the img2text-input slug is shared, so no new
    spawn while ANY run is tracked (a 320s run + queue wait can exceed the
    600s gap — gap alone doesn't prevent overlap). Poison-job guard: a
    job-specific spawn failure (unreadable upload) logs + drops that head
    candidate and retries the REST of the batch this tick instead of
    head-of-line blocking the queue; dataset-wide failures (_DatasetSpawnError)
    abort the tick. Never raises (ensure_worker caller)."""
    global _last_spawn
    # Restart recovery (spec 2026-10-09): an "extracting" job with a
    # persisted ref whose run is no longer tracked (server restart) is
    # re-adopted → poll resumes → ingest runs. worker_token_hash IS NULL keeps
    # HTTP-claimed jobs (stale ref) out of the map.
    async with session_factory() as session:
        orphans = (
            await session.execute(
                select(Job)
                .where(
                    Job.status == "extracting",
                    Job.kaggle_ref.isnot(None),
                    Job.worker_token_hash.is_(None),
                )
                .order_by(Job.id)
            )
        ).scalars().all()
    # group by ref: all jobs of one run land in ONE entry (review focus:
    # spawn crash between UPDATE and map insert → adopt recovers the group)
    by_ref: dict[str, list[Job]] = {}
    for job in orphans:
        by_ref.setdefault(str(job.kaggle_ref), []).append(job)
    for ref, group in by_ref.items():
        ids = [j.id for j in group]
        run = _batch_runs.get(ref)
        if run is not None:  # live ref → merge any not-yet-tracked group members
            known = set(run["job_ids"])
            run["job_ids"].extend(i for i in ids if i not in known)
            continue
        # P2-8: adopt KHÔNG reset đồng hồ timeout — tuổi run lấy từ
        # started_at đã persist (restart recovery vẫn revert đúng hạn);
        # started_at thiếu → coi như mới (fresh, không tự kill sớm).
        started = [j.started_at for j in group if j.started_at is not None]
        age = 0.0
        if started:
            age = max(
                0.0,
                (datetime.now(timezone.utc) - min(started)).total_seconds(),
            )
        _batch_runs[ref] = {
            "ref": ref,
            "pushed_at": time.monotonic() - age,
            "job_ids": ids,
            "ingest_failures": 0,
        }
        logger.info(
            "kaggle batch: adopt ref %s jobs %s (restart recovery)",
            ref, ids,
        )
    for run in list(_batch_runs.values()):
        await _poll_batch_run(api, session_factory, run)
    if _batch_runs:  # active run(s) — shared input slug: never overlap
        return False
    now = time.monotonic()
    min_gap = await get_runtime_setting(
        session_factory, "kaggle_min_gap_seconds", settings.kaggle_min_gap_seconds
    )
    if _last_spawn and now - _last_spawn < min_gap:
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
    # batch one-run: stage ALL queued jobs (up to the cap) into ONE run
    # KAGGLE_BATCH_MAX_JOBS 0/-1 = unlimited — không slice, gom hết queued
    cap = settings.kaggle_batch_max_jobs
    candidates = queued if cap <= 0 else queued[:cap]
    while candidates:
        try:
            tracked = await _spawn_batch_run(api, session_factory, candidates)
        except _DatasetSpawnError:
            # dataset-wide (verify/refresh/push) — a smaller batch would just
            # repeat the same failure: abort, retry next tick
            _last_spawn = time.monotonic()  # anti-hammer on persistent errors
            logger.warning(
                "batch spawn failed (dataset stage/verify/push)", exc_info=True
            )
            return False
        except Exception:
            _last_spawn = time.monotonic()  # anti-hammer on persistent errors
            logger.warning(
                "batch spawn failed job=%s", candidates[0].id, exc_info=True
            )
            # per-job poison (head's storage read failed before any Kaggle
            # call): drop the head, retry the REST this tick — a poison job
            # must not block the queue. Ceiling: a mid-list poison drops
            # innocent heads first; they stay queued and spawn next tick.
            candidates = candidates[1:]
            continue
        if not tracked:
            # claimed mid-push: the pushed kernel still runs — never start
            # a second one this tick (shared img2text-input slug)
            return False
        ref, run = next(iter(_batch_runs.items()))
        logger.info(
            "kaggle batch: pushed jobs %s → kernel %s",
            run["job_ids"], ref,
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
        if mode == "session":
            # Spec session worker (2026-10-16 T6): 1 kernel session loop
            return await _ensure_sessions(api, session_factory)
        if mode != "loop":
            # Plan K5 (batch): drive the standalone script kernel per job
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
        if _last_spawn and now - _last_spawn < min_gap:
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
