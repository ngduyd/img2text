"""Task 4: worker protocol — next / heartbeat / result / fail (brief Step 1)."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.core.models import Job

async def test_next_claims_and_returns_payload(worker_client, seed_job):
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200
    b = r.json()
    assert b["job_id"] == seed_job and b["worker_token"] and "uploads/" in b["file_url"]

async def test_next_empty_204(worker_client):
    assert (await worker_client.get("/api/jobs/next")).status_code == 204

async def test_next_wrong_key_401(client_no_runner_key):
    assert (await client_no_runner_key.get("/api/jobs/next")).status_code == 401

async def test_concurrent_next_single_claim(worker_client, worker_client2, seed_job):
    rs = await asyncio.gather(worker_client.get("/api/jobs/next"),
                              worker_client2.get("/api/jobs/next"))
    claimed = [r for r in rs if r.status_code == 200]
    assert len(claimed) == 1 and sum(r.status_code == 204 for r in rs) == 1

async def test_heartbeat_extends(worker_client, db_session, seed_job):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    old_lease = job.lease_expires_at
    r = await worker_client.post(f"/api/jobs/{seed_job}/heartbeat",
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    new_lease = datetime.fromisoformat(r.json()["lease_expires_at"])
    assert new_lease > old_lease  # heartbeat actually extends the lease

async def test_result_422_bad_bbox_shape(worker_client, seed_job, VALID_RESULT_JSONB):
    """spec §4 bbox = [x1, y1, x2, y2]; len!=4 → 422 (Plan D crop safety)."""
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    bad = deepcopy(VALID_RESULT_JSONB); bad["pages"][0]["regions"][0]["bbox"] = [1, 2, 3]
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=bad,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422

async def test_result_done(worker_client, db_session, seed_job, VALID_RESULT_JSONB, monkeypatch):
    """POST /result → result stored (rendering) → auto-output → done."""
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=VALID_RESULT_JSONB,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    from app.services.job_results import drain_auto_output
    await drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done" and job.result["model_version"] and job.worker_token_hash is None

async def test_result_409_when_not_running(worker_client, db_session, seed_job, VALID_RESULT_JSONB):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    await worker_client.post(f"/api/jobs/{seed_job}/fail", json={"error": "boom"},
                             headers={"Authorization": f"Bearer {tok}"})
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=VALID_RESULT_JSONB,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 409

async def test_result_422_bad_verdict_enum(worker_client, seed_job, VALID_RESULT_JSONB):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    bad = deepcopy(VALID_RESULT_JSONB); bad["pages"][0]["regions"][0]["verdict"] = "madeup"
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=bad,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422

async def test_result_409_lease_expired(worker_client, db_session, seed_job, VALID_RESULT_JSONB):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=VALID_RESULT_JSONB,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 409                       # expired lease ≠ runnable
    # requeue + reclaimable path covered in Task 5 (reaper)

async def test_heartbeat_lease_expired_409(worker_client, db_session, seed_job):
    """Fix round 1 minor: heartbeat on expired lease → 409, not 200."""
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    r = await worker_client.post(f"/api/jobs/{seed_job}/heartbeat",
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 409

async def test_worker_auth_accepts_valid_token(worker_client, seed_job):
    """P2 #16: heartbeat với token claim hợp lệ → 200 (hash so khớp)."""
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/heartbeat",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200

async def test_worker_auth_rejects_invalid_token(worker_client, seed_job):
    """P2 #16: sai token → 401 (hash không khớp)."""
    await worker_client.get("/api/jobs/next")
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/heartbeat",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401
