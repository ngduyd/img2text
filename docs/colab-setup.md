# Colab — worker setup

The worker is `worker/colab_notebook.ipynb` (Plan C). It is an unreliable batch
runner: the server queue survives its death (lease reaper re-queues), so
disconnects are never fatal.

## 1. Runtime

Colab → Runtime → Change runtime type → **GPU** (T4). CPU-only will OOM/fail on
PaddleOCR-VL. Free-tier disconnects after idle are expected.

## 2. Upload files

Upload into `/content/`:

- `worker/colab_notebook.ipynb` (run from `/content/`)
- `worker/pipeline.py` and `worker/verdict.py` — the loop cell does
  `sys.path.insert(0, "worker")` and `from pipeline import run_job`, so keep the
  notebook in `/content/` and the two modules in `/content/worker/`.

Also upload one test image as `/content/TA.jpg` (smoke cell input).

## 3. Colab Secrets (🔑)

Runtime → Manage secrets:

| Secret     | Value                                                        |
|------------|--------------------------------------------------------------|
| `BASE_URL` | deployed server base URL, e.g. `https://app.example.com` (same as server `BASE_URL` env) |
| `RUNNER_KEY` | **same value** as the server env `RUNNER_KEY` (`deploy/.env`) |

Secrets are never printed: the notebook prints only
`RUNNER_KEY: set ( N chars )`. The secrets cell retries every 5 s until both
are set.

## 4. Cell order

Run in this order (matches the notebook's own markdown header):

1. **Setup** — `!apt-get -qq install -y poppler-utils` + pip install
   (`paddlepaddle-gpu paddleocr httpx opencv-python-headless rapidfuzz pypdf pillow numpy`) +
   `!pdftoppm -v` sanity check.
2. **Secrets** — retry loop until `BASE_URL` + `RUNNER_KEY` resolve.
3. **Smoke — ONCE, manually, before the loop.** Upload `TA.jpg`, run the cell.
   It loads the pinned pipeline and prints actual `res.json` keys; record them
   in [docs/colab-smoke-checklist.md](docs/colab-smoke-checklist.md) and compare
   against the adapter assumption in `worker/pipeline.py`
   (`res_json_to_regions`: `layout` list with `type`/`bbox`/`rec_texts`/
   `rec_scores` + top-level `markdown`). A shape mismatch changes the adapter —
   fix before running the loop.
4. **Init** — `PaddleOCRVL(pipeline_version="v1.5",
   vl_rec_model_name="PaddleOCR-VL-1.5-0.9B",
   layout_detection_model_name="PP-DocLayoutV3")` (reuses the smoke cell's
   `PIPELINE` when present — no double model load).
5. **Loop** — `run_job(BASE_URL, RUNNER_KEY, ...)`:
   `GET /api/jobs/next` (Bearer `RUNNER_KEY`) → per page: heartbeat per page (lease 45 min) →
   `POST /api/jobs/{id}/result`. Auth failure (`RunnerAuthError`) stops the loop
   loudly (quota/key issue) — check the secret matches `deploy/.env`.

After each release: re-run the smoke cell per
[docs/colab-smoke-checklist.md](docs/colab-smoke-checklist.md).

## Expected latency — batch, not realtime

Jobs are claimed one at a time; each job rasterizes pages (`pdftoppm -r 200`),
runs the VLM per page on a free-tier GPU, and posts once at the end. Expect
**minutes per page/job, not seconds**; the UI polls every 3 s while `running`.
Free-tier GPU availability is Colab's — queue wait is normal.

## Disconnects — worker is resumable

Colab may disconnect mid-job. Nothing is lost: the server's lease reaper
(APScheduler, every 1 min) re-queues any `running` job whose lease expired
(lease 45 min, heartbeat per page (lease 45 min) while alive) and clears the
`worker_token`. To resume: reopen the notebook, re-run cells 1–2 (secrets),
then cell 5 (loop) — the re-queued job is claimed again (retry redoes all
pages, idempotent overwrite). Claiming is atomic (`SELECT … FOR UPDATE SKIP
LOCKED`), so a second loop cell never duplicates a job; still, one loop cell
per session is the intended usage.
