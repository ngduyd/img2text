# Plan G — Deploy, Docs, Env Parity

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Runnable deployment — docker compose (postgres + server + nginx + built SPA), `.env.example` parity with Settings, reference.docx generation, R2/Colab setup docs, end-to-end manual smoke checklist.

**Architecture:** nginx serves `web/dist` SPA + reverse-proxies `/api/` (client_max_body_size 60m). Server container runs uvicorn (single worker — rate limiter ceiling documented). Compose file for prod mirrors test compose minus test DB name.

**Tech Stack:** docker compose v2, nginx, pandoc+weasyprint in server image (`deploy/Dockerfile`), python-docx.

**Spec:** §11 env, §12 repo layout, §14 deployment, §5 lifecycle rules, §13 CI note.

**Depends on:** Plans A–F (all green suites); Plan D Task 3 (`make_reference_docx.py` exists).

## Global Constraints

- `deploy/.env.example` must contain EXACTLY the Settings fields (parity test enforces — drift fails CI).
- `deploy/docker-compose.yml` services: `postgres` (postgres:16-alpine), `server` (build `deploy/Dockerfile`), `nginx` (image nginx:alpine, mounts `deploy/nginx.conf` + `web/dist`), ports 80:80.
- `deploy/Dockerfile`: python:3.11-slim + `apt-get install pandoc weasyprint deps poppler-utils` + `pip install ./server`.
- `deploy/nginx.conf`: `client_max_body_size 60m`; `/api/` → `proxy_pass http://server:8000`; SPA fallback `try_files $uri /index.html`; `/healthz` proxied.
- Docs: `docs/r2-setup.md` (bucket, API token, lifecycle: uploads 30d, exports 7d), `docs/colab-setup.md` (secrets BASE_URL+RUNNER_KEY, pip/apt installs, notebook run, smoke checklist link), `README.md` quickstart.
- E2E manual checklist `docs/e2e-checklist.md`: register → admin grants → upload 3-page PDF → Colab run → preview issues → edit → export docx → admin stats row → logs show requests.
- TDD where automatable (compose config, env parity, reference styles); manual items explicitly labeled.

## Review Focus

- `.env.example` drift vs Settings fields (parity test — catches silently-missing new envs).
- nginx body limit vs 50 MB uploads + multipart overhead (60m chosen; test = compose config grep, manual real-upload check in checklist).
- Single uvicorn worker documented next to limiter code (README + compose comment).
- weasyprint/pandoc present in server image (Dockerfile test: run container `pandoc --version && python -c "import weasyprint"`).

---

### Task 1: Dockerfile + compose + nginx + env parity test

**Files:**
- Create: `deploy/Dockerfile`, `deploy/docker-compose.yml`, `deploy/nginx.conf`, `deploy/.env.example`, `server/tests/test_env_parity.py`
- Modify: `server/app/config.py` (ensure `Settings.model_fields` is single source)

**Interfaces:**
- Consumes: Plan A `Settings`.
- Produces: compose stack up with `docker compose -f deploy/docker-compose.yml config -q` valid; `.env.example` keys == Settings field names (uppercased).

- [ ] **Step 1: Failing test** `server/tests/test_env_parity.py`:

```python
def test_env_example_matches_settings_fields():
    fields = {n.upper() for n in Settings.model_fields}
    example = Path(__file__).parents[2] / "deploy" / ".env.example"
    keys = {ln.split("=")[0].strip() for ln in example.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")}
    assert fields <= keys, f"missing in .env.example: {fields - keys}"
    assert keys <= fields, f"stale keys in .env.example: {keys - fields}"
```

- [ ] **Step 2: Run → FAIL** (`cd server && pytest tests/test_env_parity.py -v`)
- [ ] **Step 3: Implement** Dockerfile/compose/nginx/.env.example per Global Constraints; `.env.example` contains every Settings field with placeholder values (R2_*, SMTP_*, DATABASE_URL, APP_SECRET, BASE_URL, RUNNER_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, LOG_PATH).
- [ ] **Step 4: Run → PASS** + `docker compose -f deploy/docker-compose.yml config -q` exits 0; `docker build -f deploy/Dockerfile -t img2text-test . && docker run --rm img2text-test bash -c "pandoc --version | head -1 && python -c 'import weasyprint'"` succeeds.
- [ ] **Step 5: Commit** `feat(deploy): docker stack, nginx, env parity`

---

### Task 2: reference.docx generation documented + rebuild test

**Files:**
- Create: `server/tests/test_reference_rebuild.py`
- Modify: `docs/r2-setup.md` (reference to `deploy/make_reference_docx.py`)

**Interfaces:**
- Consumes: Plan D `make_reference_docx`.
- Produces: rebuild-on-demand procedure documented; test guards committed artifact not stale.

- [ ] **Step 1: Failing test**:

```python
def test_committed_reference_matches_builder(tmp_path):
    from deploy.make_reference_docx import make_reference_docx
    fresh = tmp_path / "ref.docx"; make_reference_docx(str(fresh))
    committed = Path(__file__).parents[2] / "deploy" / "reference.docx"
    assert committed.exists()
    a = Document(str(fresh)); b = Document(str(committed))
    assert {s.name for s in a.styles} == {s.name for s in b.styles}
```

- [ ] **Step 2: Run → FAIL** (missing committed file or stale styles) → **Step 3: Implement** run `python deploy/make_reference_docx.py deploy/reference.docx`, commit; test imports via path insert (`sys.path.insert(0, repo_root)`) — note in test docstring.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(deploy): committed reference.docx + staleness guard`

---

### Task 3: Docs (README, R2, Colab) + E2E checklist

**Files:**
- Create: `README.md`, `docs/r2-setup.md`, `docs/colab-setup.md`, `docs/e2e-checklist.md`
- Modify: — (none)

**Interfaces:**
- Consumes: all prior plans' endpoints and env.
- Produces: docs per Global Constraints; checklist items map 1:1 to spec §2 "In (MVP)" bullets (each bullet gets a checkbox with expected observable result).

- [ ] **Step 1: Write docs** (no automated test — content verification manual):
  - `README.md`: stack diagram (text), quickstart `docker compose -f deploy/docker-compose.test.yml up -d --wait && cd server && pytest -v && cd ../worker && pytest -v && cd ../web && npm test`, prod up, **"Single uvicorn worker by design — in-process rate limits assume it."**
  - `docs/r2-setup.md`: bucket create, API token (Object Read & Write, scoped), lifecycle rules table (prefix uploads/ 30d, exports/ 7d), `.env` fill.
  - `docs/colab-setup.md`: runtime GPU, secrets BASE_URL/RUNNER_KEY, `!apt-get install poppler-utils`, pip line matching Plan C notebook, upload `worker/colab_notebook.ipynb`, run cells in order, link `docs/colab-smoke-checklist.md`.
  - `docs/e2e-checklist.md`: 12 checkboxes covering spec §2 In-scope list + 2 security checks (preview XSS payload renders inert; other user's job 403).
- [ ] **Step 2: Manual verification** (human gate): run checklist on a real stack end-to-end; tick boxes; file issues for any miss into the owning plan's task.
- [ ] **Step 3: Commit** `docs: quickstart, r2/colab setup, e2e checklist`

---

### Task 4: Full-suite gate + merge readiness

**Files:**
- Modify: — (none; verification task)

- [ ] **Step 1: Run every suite in order** (record output in commit message body):

```bash
docker compose -f deploy/docker-compose.test.yml up -d --wait
cd server && pytest -v          # Plans A,B,D,E + parity
cd ../worker && pytest -v       # Plan C
cd ../web && npm test && npm run build   # Plan F
docker compose -f deploy/docker-compose.yml config -q
```

- [ ] **Step 2: Fix any red** (root-cause in owning module; re-run; never weaken an assertion to go green — escalate to plan owner instead).
- [ ] **Step 3: Commit** `chore: full suite green gate`

---

**Plan G done when:** all suites green, compose config valid, docs committed, e2e checklist ticked on a real run.
