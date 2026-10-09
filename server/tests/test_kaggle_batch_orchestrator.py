"""Plan K5 — batch orchestration: queued job → stage input → dataset
delete+create → push script kernel → poll → result.json ingest.

Kaggle never called live: a per-test stub replaces orch._api() (the K2 file
installs a sys.modules stub for its own tests; dispatch is covered on both
sides here + in test_kaggle_orchestrator.py). Storage is the moto driver
from the conftest app fixture, injected through the orch._get_storage seam.
"""

import asyncio
import json
import hashlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.models import Job, User
from app.core.schemas import ResultBody
from app.services import kaggle_orchestrator as orch
from app.services.job_results import drain_auto_output, store_batch_result
from tests.conftest import PNG_1PX

DEPLOY_KAGGLE = Path(__file__).parents[2] / "deploy" / "kaggle"

RESULT_DOC = {
    "source_pdf": "uploads/x.png",
    "dpi": 200,
    "pages": [
        {
            "page": 1,
            "image": "/tmp/pre/page_0001.png",
            "width": 800,
            "height": 600,
            "preprocess": {"skew_deg": 0.0, "shadow_removed": True, "resized": False},
            "blocks": [
                {"id": "p1_b0", "order": 0, "type": "doc_title",
                 "bbox": [10, 10, 400, 60], "text": "Báo cáo", "empty": False},
                {"id": "p1_b1", "order": 1, "type": "paragraph_title",
                 "bbox": [10, 70, 400, 100], "text": "Mục 1", "empty": False},
                {"id": "p1_b2", "order": 2, "type": "table",
                 "bbox": [10, 110, 400, 300],
                 "text": "<table><tr><td>1</td></tr></table>", "empty": False},
                {"id": "p1_b3", "order": 3, "type": "image",
                 "bbox": [10, 310, 400, 500], "text": "hình minh họa", "empty": False},
                {"id": "p1_b4", "order": 4, "type": "text",
                 "bbox": [10, 510, 400, 550], "text": "   ", "empty": True},
            ],
        },
        {
            "page": 2,
            "image": "/tmp/pre/page_0002.png",
            "width": None,
            "height": None,
            "preprocess": {},
            "blocks": [
                {"id": "p2_b0", "order": 0, "type": "text",
                 "bbox": [5, 5, 300, 40], "text": "Trang hai", "empty": False},
            ],
        },
    ],
}

class _NotFound(Exception):
    """kaggle 2.2.4 missing-dataset shape: requests HTTPError (403/404)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"{code} Client Error")
        self.response = SimpleNamespace(status_code=code)


class BatchStubKaggleApi:
    """Live-shaped KaggleApi: enum-like status, folder dataset APIs, output pull.

    Dataset state mirrors production: the img2text-input dataset EXISTS
    (private — dataset_list search never returns it) and serves the OLD
    input file until a successful delete+create replaces it."""

    def __init__(self) -> None:
        self.calls: list = []  # (method, ...) in call order
        self.status = {"status": SimpleNamespace(name="COMPLETE")}
        self.dataset_items: list = []
        self.result_doc: dict | None = None
        self.output_error: Exception | None = None
        self.dataset_exists = True  # private dataset present (prod state)
        self.dataset_files = ["TA.jpg"]  # OLD input served by list_files
        self.stale_after_create = False  # create OK but files stay old

    def dataset_list(self, search=None):
        self.calls.append(("dataset_list", search))
        return self.dataset_items

    def dataset_status(self, ref):
        self.calls.append(("dataset_status", ref))
        if not self.dataset_exists:
            raise _NotFound(403)
        return "ready"

    def dataset_list_files(self, ref):
        self.calls.append(("dataset_list_files", ref))
        if not self.dataset_exists:
            raise _NotFound(403)
        return SimpleNamespace(
            dataset_files=[SimpleNamespace(name=n) for n in self.dataset_files]
        )

    def dataset_delete(self, owner, slug, no_confirm=False):
        self.calls.append(("dataset_delete", f"{owner}/{slug}"))
        self.dataset_exists = False  # files linger until create (eventual)
        return True

    def dataset_create_new(self, folder):
        meta = json.loads((Path(folder) / "dataset-metadata.json").read_text())
        files = sorted(p.name for p in Path(folder).iterdir())
        self.calls.append(("dataset_create_new", meta["id"], files))
        self.dataset_exists = True
        if not self.stale_after_create:
            self.dataset_files = [f for f in files if f != "dataset-metadata.json"]
        return {"ref": meta["id"]}

    def kernels_push(self, path):
        meta = json.loads((Path(path) / "kernel-metadata.json").read_text())
        files = sorted(p.name for p in Path(path).iterdir())  # dir dies after push
        self.calls.append(("kernels_push", path, meta, files))
        return meta["id"]

    def kernels_status(self, ref):
        self.calls.append(("kernels_status", ref))
        return self.status

    def kernels_output(self, ref, path=None, quiet=False):
        self.calls.append(("kernels_output", ref, path))
        if self.output_error is not None:
            raise self.output_error  # transient pull failure (test knob)
        assert self.result_doc is not None, "kernels_output before test set result_doc"
        (Path(path) / "result.json").write_text(
            json.dumps(self.result_doc, ensure_ascii=False), encoding="utf-8"
        )
        return None

    # K2 surface (only touched by the mode=loop dispatch test)
    def dataset_create_version(self, folder, version_notes=None):
        self.calls.append(("dataset_create_version", folder))
        return {"folder": folder}

@pytest.fixture(autouse=True)
def _reset_batch_state(monkeypatch):
    monkeypatch.setattr(orch, "_last_spawn", 0.0)
    monkeypatch.setattr(orch, "_batch_runs", {})
    yield

@pytest.fixture
def api(monkeypatch):
    stub = BatchStubKaggleApi()
    monkeypatch.setattr(orch, "_api", lambda: stub)
    return stub

@pytest.fixture
def kaggle_batch_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "kaggle_mode", "batch")
    monkeypatch.setattr(settings, "kaggle_username", "testuser")
    monkeypatch.setattr(settings, "kaggle_key", "testkey")
    monkeypatch.setattr(settings, "kaggle_kernel_ref", "testuser/img2text-worker")
    monkeypatch.setattr(settings, "kaggle_stage_src", str(DEPLOY_KAGGLE))
    monkeypatch.setattr(settings, "kaggle_stage_dir", str(tmp_path / "kaggle-kernel"))
    return settings

@pytest.fixture
def storage_env(app, storage_spy, monkeypatch):
    """moto driver (spied) through the orchestrator's storage seam."""
    monkeypatch.setattr(orch, "_get_storage", lambda: app.state.storage)
    return storage_spy

def _pushes(api) -> list:
    return [c for c in api.calls if c[0] == "kernels_push"]

async def test_batch_stale_input_dataset_skips_kernel_push(
    kaggle_batch_env, api, storage_env, seed_job, db_session, monkeypatch, caplog
):
    """BUG (dataset stale): delete+create return but dataset_list_files still
    serves the OLD file (TA.jpg) → kernels_push must NOT run; the spawn
    failure skips the job (stays queued, retried next tick)."""
    monkeypatch.setattr(orch, "_INPUT_VERIFY_TIMEOUT", 0.05)
    monkeypatch.setattr(orch, "_INPUT_VERIFY_INTERVAL", 0.01)
    api.stale_after_create = True
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False
    assert _pushes(api) == []  # NEVER pushed into the old dataset
    assert any(
        "batch spawn failed" in r.getMessage() for r in caplog.records
    )
    assert orch._batch_runs == {}
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "queued"  # untouched — retried next tick

async def test_batch_verifies_input_files_before_kernel_push(
    kaggle_batch_env, api, storage_env, seed_job, db_session
):
    """list_files shows the staged upload → push proceeds. Also pins the
    private-dataset exists check: dataset_status sees it (dataset_list search
    returns []), so delete runs and the verify call precedes kernels_push."""
    assert await orch.ensure_worker(SessionLocal) is True
    job = await db_session.get(Job, seed_job)
    staged = Path(job.storage_key).name  # sha.<ext>
    assert ("dataset_status", "testuser/img2text-input") in api.calls
    assert ("dataset_delete", "testuser/img2text-input") in api.calls
    files_checks = [c for c in api.calls if c[0] == "dataset_list_files"]
    assert files_checks and files_checks[0][1] == "testuser/img2text-input"
    kinds = [c[0] for c in api.calls]
    assert kinds.index("dataset_list_files") < kinds.index("kernels_push")
    assert staged in api.dataset_files  # served file == the staged upload

async def test_batch_happy_flow_spawn_then_complete_ingest(
    kaggle_batch_env, api, storage_env, seed_job, db_session, monkeypatch
):
    api.result_doc = RESULT_DOC
    # tick 1: queued → stage input → dataset delete+create → push
    assert await orch.ensure_worker(SessionLocal) is True
    job = await db_session.get(Job, seed_job)
    assert job.storage_key.startswith("uploads/")
    storage_env.get.assert_awaited_with(job.storage_key)  # staged from storage
    creates = [c for c in api.calls if c[0] == "dataset_create_new"]
    assert creates[0][1] == "testuser/img2text-input"
    assert f"{job.storage_key.rsplit('/', 1)[-1]}" in creates[0][2]  # sha.<ext> staged
    assert "dataset-metadata.json" in creates[0][2]
    pushes = _pushes(api)
    assert len(pushes) == 1
    _method, _path, meta, files = pushes[0]
    assert meta["id"] == "testuser/img2text-batch"
    assert meta["dataset_sources"] == ["testuser/img2text-input"]  # input dataset ONLY
    assert meta["kernel_type"] == "script"
    assert meta["enable_gpu"] is True
    assert "img2text_batch.py" in files and "kernel-metadata.json" in files
    assert seed_job in orch._batch_runs
    # spec 2026-10-09: push OK → status "extracting" + kernel ref persisted
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "extracting" and job.started_at is not None
    assert job.kaggle_ref == "testuser/img2text-batch"
    assert job.lease_expires_at is not None and job.worker_token is None
    # one layout OK → the auto-output completion rule ends at done
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    # tick 2: enum-shaped status → complete → output pulled → ingest
    assert await orch.ensure_worker(SessionLocal) is False
    assert any(
        c[0] == "kernels_output" and c[1] == "testuser/img2text-batch"
        for c in api.calls
    )
    assert orch._batch_runs == {}
    await drain_auto_output()  # rendering → done only after the auto-output task
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done" and job.finished_at is not None
    assert job.worker_token is None and job.lease_expires_at is None
    res = job.result
    assert res["model_version"] == orch.BATCH_MODEL_VERSION
    assert res["gpu_seconds"] == 0.0
    assert res["warnings"] == []
    assert len(res["pages"]) == 2
    p1 = res["pages"][0]
    assert p1["index"] == 1 and p1["width"] == 800 and p1["height"] == 600
    # image + empty-text blocks dropped; doc_title/paragraph_title/table kept
    assert [r["text"] for r in p1["regions"]] == [
        "Báo cáo",
        "Mục 1",
        "<table><tr><td>1</td></tr></table>",
    ]
    assert all(
        set(r) == {"id", "bbox", "text", "verdict", "placeholder"}
        and r["verdict"] == "ok"
        and r["placeholder"] is False
        for r in p1["regions"]
    )
    assert p1["markdown"].startswith("# Báo cáo")
    assert "\n\n## Mục 1" in p1["markdown"]
    assert "<table><tr><td>1</td></tr></table>" in p1["markdown"]
    p2 = res["pages"][1]
    assert p2["index"] == 2 and p2["width"] == 0 and p2["height"] == 0
    assert p2["markdown"] == "Trang hai"
    assert res["markdown"] == p1["markdown"] + "\n\n---\n\n" + p2["markdown"]
    # validated against the exact worker result shape
    ResultBody.model_validate(res)

async def test_batch_preprocess_ceiling_warns_and_ingests_whole_file(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog, monkeypatch
):
    api.result_doc = RESULT_DOC
    job = await db_session.get(Job, seed_job)
    job.preprocess = '{"pages": [1], "rotate": {"1": 90}}'
    await db_session.commit()
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)  # before ingest
    assert await orch.ensure_worker(SessionLocal) is True  # spawn
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False  # complete → ingest
    assert any("bỏ qua preprocess" in r.getMessage() for r in caplog.records)
    # ingest → rendering; one layout OK → done after the auto-output task
    await drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"
    assert len(job.result["pages"]) == 2  # whole file, selection ignored

async def test_batch_ingest_marks_rendering_then_done_after_auto_output(
    kaggle_batch_env, api, storage_env, seed_job, db_session, monkeypatch
):
    """spec 2026-10-09: ingest success → status "rendering" (result stored,
    layout still in flight); auto-output OK → "done"."""
    api.result_doc = RESULT_DOC
    gate = asyncio.Event()

    async def _gated_auto(job, storage):
        await gate.wait()  # holds the job in "rendering" deterministically
        return True

    monkeypatch.setattr("app.routers.exports.auto_generate_output", _gated_auto)
    assert await orch.ensure_worker(SessionLocal) is True  # spawn → extracting
    assert await orch.ensure_worker(SessionLocal) is False  # complete → ingest
    try:
        db_session.expire_all()
        job = await db_session.get(Job, seed_job)
        assert job.status == "rendering" and job.result is not None
    finally:
        gate.set()  # never leak a gated task past a failing assertion
        await drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done" and job.failed_step is None

async def test_batch_spawn_marks_job_extracting_with_kaggle_ref(
    kaggle_batch_env, api, storage_env, seed_job, db_session
):
    """spec 2026-10-09: kernels_push OK → status=extracting,
    kaggle_ref persisted (restart adoption), started_at=now,
    lease_expires_at=now+kaggle_timeout (reaper must not requeue mid-run)."""
    assert await orch.ensure_worker(SessionLocal) is True
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "extracting"
    assert job.kaggle_ref == "testuser/img2text-batch"
    assert job.started_at is not None and job.worker_token is None
    expected = datetime.now(timezone.utc) + timedelta(
        seconds=settings.kaggle_timeout
    )
    assert abs((job.lease_expires_at - expected).total_seconds()) < 60
    assert job.lease_expires_at > datetime.now(timezone.utc)

async def test_batch_failed_marks_failed_with_extracting_step(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog, monkeypatch
):
    """spec 2026-10-09 (supersedes the revert-and-respawn of 2263d24): a
    FAILED kernel fails the job at step "extracting" — no silent respawn;
    the owner retries through POST /api/jobs/{id}/retry."""
    assert await orch.ensure_worker(SessionLocal) is True
    api.status = {"status": SimpleNamespace(name="FAILED")}
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False  # poll drops ref
    assert orch._batch_runs == {}  # ref deleted
    assert any("failed at step extracting" in r.getMessage() for r in caplog.records)
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "failed" and job.failed_step == "extracting"
    assert job.lease_expires_at is None and job.finished_at is not None
    # P2-3: the owner sees WHY — error names the kernel status
    assert job.error == "Kaggle kernel failed"
    # no auto-respawn: only queued jobs are spawn candidates (even gapless)
    monkeypatch.setattr(settings, "kaggle_min_gap_seconds", 0)
    assert await orch.ensure_worker(SessionLocal) is False
    assert len(_pushes(api)) == 1

async def test_batch_cancelled_marks_failed_with_extracting_step(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog
):
    """cancelled kernel (user cancel on Kaggle UI / auto-cancel) → ref dropped
    + failed + failed_step=extracting, same as failed/error (no 3h hang)."""
    assert await orch.ensure_worker(SessionLocal) is True
    api.status = {"status": SimpleNamespace(name="CANCELLED")}
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False  # poll drops ref
    assert orch._batch_runs == {}  # ref deleted
    assert any("failed at step extracting" in r.getMessage() for r in caplog.records)
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "failed" and job.failed_step == "extracting"
    assert job.lease_expires_at is None

async def test_batch_timeout_drops_ref_with_warning(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog
):
    assert await orch.ensure_worker(SessionLocal) is True
    run = orch._batch_runs[seed_job]
    run["pushed_at"] = time.monotonic() - settings.kaggle_timeout - 1
    api.status = {"status": SimpleNamespace(name="RUNNING")}
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False
    assert orch._batch_runs == {}
    assert any("kaggle_timeout" in r.getMessage() for r in caplog.records)
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    # D1: timeout path reverts running → queued, lease cleared
    assert job.status == "queued" and job.lease_expires_at is None

async def test_batch_timeout_status_marks_failed_with_extracting_step(
    kaggle_batch_env, api, storage_env, seed_job, db_session, monkeypatch
):
    """P2-2 (spec: timeout → failed+extracting, replaces the 2263d24 revert):
    literal kernel status TIMEOUT is terminal — ref dropped, failed +
    failed_step=extracting + error naming the status, NO queued revert,
    NO respawn."""
    assert await orch.ensure_worker(SessionLocal) is True
    api.status = {"status": SimpleNamespace(name="TIMEOUT")}
    assert await orch.ensure_worker(SessionLocal) is False  # poll drops ref
    assert orch._batch_runs == {}
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "failed" and job.failed_step == "extracting"
    assert job.error == "Kaggle kernel timeout"
    assert job.lease_expires_at is None and job.finished_at is not None
    monkeypatch.setattr(settings, "kaggle_min_gap_seconds", 0)
    assert await orch.ensure_worker(SessionLocal) is False  # not respawned
    assert len(_pushes(api)) == 1

async def _extra_queued_job(auth_client) -> int:
    """Second real upload — different bytes → different sha256 storage key."""
    r = await auth_client.post(
        "/api/jobs", files={"file": ("t2.png", PNG_1PX + b"seed2", "image/png")}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]

async def test_revert_skips_worker_claimed_extracting_job(
    kaggle_batch_env, api, storage_env, seed_job, db_session
):
    """Rider: revert guard (status=extracting AND worker_token IS NULL) — a
    job claimed by an HTTP worker is NOT clobbered back to queued."""
    assert await orch.ensure_worker(SessionLocal) is True  # job → extracting
    job = await db_session.get(Job, seed_job)
    job.worker_token = "claimed-tok"
    await db_session.commit()
    await orch._revert_job_queued(SessionLocal, seed_job, "kernel failed")
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "extracting" and job.worker_token == "claimed-tok"
    assert job.lease_expires_at is not None  # lease untouched too

async def test_spawn_rowcount_zero_warns_and_skips_tracking(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog
):
    """Rider: job claimed between the candidate select and the extracting-mark
    UPDATE (rowcount 0) → warning + no _batch_runs entry (untracked)."""
    job = await db_session.get(Job, seed_job)  # queued candidate
    await db_session.execute(
        update(Job)
        .where(Job.id == seed_job)
        .values(status="extracting", worker_token="claimed-tok")
    )
    await db_session.commit()  # claimed by an "HTTP worker" before spawn
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch._spawn_batch_run(api, SessionLocal, job) is False
    assert any("run not tracked" in r.getMessage() for r in caplog.records)
    assert orch._batch_runs == {}  # not tracked
    assert len(_pushes(api)) == 1  # push happened, tracking skipped
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "extracting" and job.worker_token == "claimed-tok"

async def test_batch_single_active_run_blocks_new_spawn(
    kaggle_batch_env, api, storage_env, seed_job, auth_client, db_session, monkeypatch
):
    """P1-1: shared img2text-input slug — no new spawn while a run is active,
    even when the gap has already elapsed (320s run + queue wait > 600s gap)."""
    monkeypatch.setattr(settings, "kaggle_min_gap_seconds", 0)
    assert await orch.ensure_worker(SessionLocal) is True  # job1 spawned
    job2 = await _extra_queued_job(auth_client)
    api.status = {"status": SimpleNamespace(name="RUNNING")}
    assert await orch.ensure_worker(SessionLocal) is False  # poll → still active
    assert len(_pushes(api)) == 1  # NO new kernels_push
    assert list(orch._batch_runs) == [seed_job]
    assert seed_job != job2  # job2 waited, not pushed

async def test_batch_poison_job_does_not_block_queue(
    kaggle_batch_env, api, storage_env, seed_job, auth_client, db_session, caplog
):
    """P1-1/P1-2: first candidate's upload missing → spawn failure logs +
    moves to the NEXT queued candidate in the same tick."""
    job2 = await _extra_queued_job(auth_client)
    job1_key = (await db_session.get(Job, seed_job)).storage_key
    await storage_env.delete_prefix(job1_key)  # storage.get → KeyError
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is True
    assert any(
        "batch spawn failed job=" in r.getMessage() for r in caplog.records
    )
    assert list(orch._batch_runs) == [job2]  # job2 spawned, job1 skipped
    creates = [c for c in api.calls if c[0] == "dataset_create_new"]
    assert len(creates) == 1
    staged_name = hashlib.sha256(PNG_1PX + b"seed2").hexdigest() + ".png"
    assert staged_name in creates[0][2]  # job2's file, not job1's
    assert len(_pushes(api)) == 1

async def test_batch_output_failure_keeps_ref_and_retries(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog, monkeypatch
):
    """P2-5: transient kernels_output failure → ref kept (no GPU re-run),
    pull retried next tick, success ingests."""
    api.result_doc = RESULT_DOC
    assert await orch.ensure_worker(SessionLocal) is True  # spawn
    api.output_error = RuntimeError("kernels_output transient")
    with caplog.at_level("WARNING", logger=orch.logger.name):
        assert await orch.ensure_worker(SessionLocal) is False
    assert seed_job in orch._batch_runs  # ref KEPT
    assert any("retry next tick" in r.getMessage() for r in caplog.records)
    api.output_error = None
    # fake BEFORE the pull tick: the completion task may start mid-tick
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    assert await orch.ensure_worker(SessionLocal) is False  # pull succeeds
    assert orch._batch_runs == {}
    await drain_auto_output()  # rendering → done after the auto-output task
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"
    assert len(_pushes(api)) == 1  # kernel NOT re-spawned for a pull retry

async def test_batch_ingest_failure_ceiling_drops_ref(
    kaggle_batch_env, api, storage_env, seed_job, db_session, caplog
):
    """P2-5: deterministic poison result → after _INGEST_MAX_FAILURES pulls
    the ref is dropped + error log (no infinite respawn loop)."""
    api.result_doc = RESULT_DOC
    assert await orch.ensure_worker(SessionLocal) is True
    api.output_error = RuntimeError("broken output")
    with caplog.at_level("WARNING", logger=orch.logger.name):
        for _ in range(orch._INGEST_MAX_FAILURES):
            assert await orch.ensure_worker(SessionLocal) is False
    assert orch._batch_runs == {}
    assert any("times — ref dropped" in r.getMessage() for r in caplog.records)
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    # D1: ingest give-up reverts running → queued (respawn path, gap-guarded)
    assert job.status == "queued" and job.lease_expires_at is None
    assert len(_pushes(api)) == 1  # gap still blocks a re-spawn this tick

async def test_restart_adopts_extracting_job_with_kaggle_ref(
    kaggle_batch_env, api, storage_env, seed_job, db_session, monkeypatch
):
    """spec 2026-10-09 restart recovery: _batch_runs empty (server restart)
    + job row "extracting" with kaggle_ref → adopted back into the map →
    poll resumes and ingest completes."""
    api.result_doc = RESULT_DOC
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    assert await orch.ensure_worker(SessionLocal) is True  # spawn
    ref = orch._batch_runs[seed_job]["ref"]
    orch._batch_runs.clear()  # simulate restart: hot index lost
    api.status = {"status": SimpleNamespace(name="RUNNING")}
    assert await orch.ensure_worker(SessionLocal) is False  # adopt + poll
    assert orch._batch_runs[seed_job]["ref"] == ref  # poll resumes
    api.status = {"status": SimpleNamespace(name="COMPLETE")}
    assert await orch.ensure_worker(SessionLocal) is False  # pull + ingest
    assert orch._batch_runs == {}
    await drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"

async def test_reaper_requeues_extracting_job_without_kaggle_ref(
    db_session, seed_job
):
    """spec 2026-10-09: "extracting" WITHOUT kaggle_ref (spawn died
    halfway) + expired lease → the reaper reverts it to queued."""
    from app.services.jobs_requeue import reap_leases

    job = await db_session.get(Job, seed_job)
    job.status = "extracting"
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    assert await reap_leases(db_session) == 1
    await db_session.refresh(job)
    assert job.status == "queued" and job.lease_expires_at is None
    assert job.kaggle_ref is None

async def test_reaper_does_not_requeue_batch_extracting_job(
    kaggle_batch_env, api, storage_env, seed_job, db_session
):
    """D1: spawn lease = now+kaggle_timeout → reap_leases sees an active
    lease and must leave the batch-extracting job alone (reaper wiring)."""
    from app.services.jobs_requeue import reap_leases

    assert await orch.ensure_worker(SessionLocal) is True
    assert await reap_leases(db_session) == 0
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "extracting"
    assert job.lease_expires_at > datetime.now(timezone.utc)

async def test_store_batch_result_guard_cases(
    db_session, seed_job, VALID_RESULT_JSONB
):
    """D1 guard: queued+unclaimed OR extracting+unclaimed+active lease →
    accepted (ingest stores the result + rendering); extracting+worker-token
    (claimed) or extracting+expired lease → reject."""
    body = ResultBody.model_validate(VALID_RESULT_JSONB)
    now = datetime.now(timezone.utc)
    job = await db_session.get(Job, seed_job)

    # extracting + token set → worker-claimed: reject, nothing written
    job.status = "extracting"
    job.worker_token = "claimed-tok"
    job.lease_expires_at = now + timedelta(seconds=60)
    await db_session.commit()
    assert await store_batch_result(db_session, seed_job, body, now=now) is False
    await db_session.refresh(job)
    assert job.status == "extracting" and job.result is None

    # extracting + lease expired → reject (reaper owns it now)
    job.worker_token = None
    job.lease_expires_at = now - timedelta(seconds=1)
    await db_session.commit()
    assert await store_batch_result(db_session, seed_job, body, now=now) is False
    await db_session.refresh(job)
    assert job.status == "extracting" and job.result is None

    # extracting + unclaimed + active lease → accepted (D1 batch path);
    # storage=None → no auto-output task, status stays at the ingest phase
    job.lease_expires_at = now + timedelta(seconds=60)
    await db_session.commit()
    assert await store_batch_result(db_session, seed_job, body, now=now) is True
    await db_session.refresh(job)
    assert job.status == "rendering" and job.lease_expires_at is None

async def test_mode_loop_dispatches_to_k2_branch(
    kaggle_batch_env, api, storage_env, seed_job, monkeypatch
):
    monkeypatch.setattr(settings, "kaggle_mode", "loop")
    batch = AsyncMock(return_value=True)
    monkeypatch.setattr(orch, "_ensure_batch_runs", batch)
    # K2 path: status check → queue → gap → stage worker kernel → bump → push
    api.status = {"status": "complete"}
    assert await orch.ensure_worker(SessionLocal) is True
    batch.assert_not_awaited()
    kinds = [c[0] for c in api.calls]
    assert "dataset_create_version" in kinds and "kernels_push" in kinds
    assert "dataset_create_new" not in kinds  # batch staging untouched

async def test_mode_batch_dispatches_to_batch_branch(
    kaggle_batch_env, api, storage_env, monkeypatch
):
    batch = AsyncMock(return_value=True)
    monkeypatch.setattr(orch, "_ensure_batch_runs", batch)
    assert await orch.ensure_worker(SessionLocal) is True
    batch.assert_awaited_once()

# --- adapter unit cases (pure, no DB) ---

def test_adapter_drops_image_and_empty_keeps_table_html():
    out = orch.adapt_batch_document(RESULT_DOC)
    body = ResultBody.model_validate(out)
    p1 = body.pages[0]
    texts = [r.text for r in p1.regions]
    assert "hình minh họa" not in texts  # type=="image" dropped (even with text)
    assert not any(t.strip() == "" for t in texts)  # empty text dropped
    assert "<table><tr><td>1</td></tr></table>" in texts  # HTML kept verbatim
    assert p1.markdown.startswith("# Báo cáo")
    assert p1.markdown.splitlines()[2].startswith("## Mục 1")

def test_adapter_title_prefixes_and_page_join():
    out = orch.adapt_batch_document(RESULT_DOC)
    assert out["markdown"].count("\n\n---\n\n") == 1  # 2 pages, one separator
    assert out["pages"][0]["markdown"].split("\n\n")[0] == "# Báo cáo"
    # bbox passthrough, verdict/placeholder batch defaults
    assert out["pages"][0]["regions"][0]["bbox"] == [10, 10, 400, 60]
    assert out["pages"][1]["regions"][0]["verdict"] == "ok"
    assert out["gpu_seconds"] == 0.0  # ceiling: wall time not tracked

def test_adapter_missing_dimensions_default_zero():
    doc = {"pages": [{"page": 1, "blocks": [
        {"id": "b", "type": "text", "bbox": None, "text": "x"}]}]}
    page = orch.adapt_batch_document(doc)["pages"][0]
    assert page["width"] == 0 and page["height"] == 0
    assert page["index"] == 1 and page["regions"][0]["bbox"] is None

def test_adapter_maps_kernel_problems_to_warnings():
    # P2-7: batch script writes "problems" (gated/missing-OCR pages) →
    # ResultBody.warnings so the UI shows what the kernel skipped.
    doc = {
        "problems": ["page_0002.png: precheck unreadable — không OCR"],
        "pages": [{"page": 1, "blocks": [
            {"id": "b", "type": "text", "bbox": None, "text": "x"}]}],
    }
    out = orch.adapt_batch_document(doc)
    assert out["warnings"] == ["page_0002.png: precheck unreadable — không OCR"]
    ResultBody.model_validate(out)

def test_api_create_dataset_raises_on_silent_error_response():
    """kaggle 2.2.4 dataset_create_new returns an error PAYLOAD (no raise)
    when the ref still exists — must raise so the spawn fails instead of
    pushing the kernel against the old dataset."""

    class SilentDict:
        def dataset_create_new(self, folder):
            return {"status": "error", "error": 'title "x" already in use'}

    class SilentObj:
        def dataset_create_new(self, folder):
            return SimpleNamespace(status="error", error="already in use")

    for stub in (SilentDict(), SilentObj()):
        with pytest.raises(RuntimeError, match="already in use"):
            orch._api_create_dataset(stub, "/tmp")

def test_norm_status_enum_and_string_forms():
    assert orch._norm_status({"status": SimpleNamespace(name="COMPLETE")}) == "complete"
    assert orch._norm_status({"status": "KernelWorkerStatus.FAILED"}) == "failed"
    assert orch._norm_status({"status": "running"}) == "running"
    assert orch._norm_status({"status": None}) is None
