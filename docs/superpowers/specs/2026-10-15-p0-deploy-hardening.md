# P0 Deploy Hardening Spec

**Date:** 2026-10-15
**Goal:** Harden production deploy by removing insecure defaults, adding fail-fast guards, and tightening compose/Dockerfile/nginx config.

## Background

8 findings from deploy verify require remediation before any production rollout. Each finding maps to a concrete task below with test criteria.

---

## Findings & Tasks

### 1-2. Remove Default Secrets; Fail-Fast on Prod

**Files:**
- `server/app/core/config.py` — Settings fields `app_secret`, `runner_key`
- `server/app/main.py` — startup validation in `lifespan`
- `deploy/.env.example` — remove default values for prod section
- `deploy/.env.dev` — keep dev defaults

**Spec:**
- `app_secret` default removed from Settings (or set to `""` with validator)
- `runner_key` default removed from Settings (or set to `""` with validator)
- On startup (`lifespan`), if `settings.env == "prod"`:
  - Raise `RuntimeError` if `app_secret` is empty, equals `"dev-secret-change-me"`, or `len(app_secret) < 32`
  - Raise `RuntimeError` if `runner_key` is empty or equals `"dev-runner-key"`
- Dev/test (`env != "prod"`) keep working with placeholder defaults

**Test Criteria (pytest):**
```python
def test_prod_fails_on_default_app_secret(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "app_secret", "dev-secret-change-me")
    with pytest.raises(RuntimeError, match="app_secret"):
        await lifespan(app).__anext__()

def test_prod_fails_on_short_app_secret(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "app_secret", "short")
    with pytest.raises(RuntimeError, match="app_secret"):
        await lifespan(app).__anext__()

def test_prod_fails_on_default_runner_key(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "runner_key", "dev-runner-key")
    with pytest.raises(RuntimeError, match="runner_key"):
        await lifespan(app).__anext__()

def test_dev_allows_defaults(monkeypatch):
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(settings, "app_secret", "dev-secret-change-me")
    monkeypatch.setattr(settings, "runner_key", "dev-runner-key")
    # should not raise
    await lifespan(app).__anext__()
```

**Commit Message:** `feat(config): remove default secrets; fail-fast on prod`

---

### 3. Fail-Fast Admin Bootstrap on Prod

**Files:**
- `server/app/services/admin_bootstrap.py` — `bootstrap_admin`
- `server/app/main.py` — lifespan calls `bootstrap_admin`

**Spec:**
- In `bootstrap_admin`, if `settings.env == "prod"` and (`admin_email` empty or `admin_password` empty): raise `RuntimeError("prod requires ADMIN_EMAIL and ADMIN_PASSWORD")`
- Dev/test: keep no-op behavior when empty

**Test Criteria:**
```python
def test_prod_fails_on_empty_admin_creds(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "admin_email", "")
    monkeypatch.setattr(settings, "admin_password", "")
    with pytest.raises(RuntimeError, match="ADMIN_EMAIL"):
        await bootstrap_admin(session, "", "")

def test_dev_allows_empty_admin_creds(db_session):
    await bootstrap_admin(db_session, "", "")  # no-op, no raise
```

**Commit Message:** `feat(admin): fail-fast bootstrap on prod with empty creds`

---

### 4. Compose: POSTGRES_PASSWORD from .env; No Host Port Publish

**Files:**
- `deploy/docker-compose.yml` — postgres service
- `deploy/.env.example` — add `POSTGRES_PASSWORD` placeholder

**Spec:**
- Postgres service: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-img2text}` (reads from `.env`, fallback for dev)
- Remove any `ports:` mapping for postgres (already not published in current compose — verify)
- `.env.example` adds `POSTGRES_PASSWORD=` under prod section with comment

**Test Criteria:**
- `docker compose -f deploy/docker-compose.yml config` shows no host port for postgres
- `grep POSTGRES_PASSWORD deploy/.env.example` returns the key

**Commit Message:** `chore(compose): POSTGRES_PASSWORD from .env; no host port publish`

---

### 5. Server Dockerfile: COPY deploy/kaggle

**Files:**
- `deploy/Dockerfile` — add COPY line

**Spec:**
- Add `COPY deploy/kaggle /app/deploy/kaggle` after `COPY deploy/reference.docx`
- Needed for `kaggle_stage_src` default (`deploy/kaggle`) to resolve at runtime

**Test Criteria:**
- `docker build -f deploy/Dockerfile .. && docker run --rm <image> ls /app/deploy/kaggle` shows kernel files

**Commit Message:** `chore(dockerfile): COPY deploy/kaggle for kernel staging`

---

### 6. LLM_BASE_URL Default Empty; Fail-Fast on Prod When Feature Enabled

**Files:**
- `server/app/core/config.py` — `llm_base_url` field default
- `server/app/main.py` — startup validation in `lifespan`

**Spec:**
- `llm_base_url: str = ""` (default empty string)
- On startup, if `settings.env == "prod"` AND `settings.kaggle_enabled` OR LLM feature flag (future) AND `llm_base_url` empty: raise `RuntimeError("prod requires LLM_BASE_URL when LLM features enabled")`
- Dev keeps `http://localhost:20128/v1` default via `.env.dev`

**Test Criteria:**
```python
def test_prod_fails_on_empty_llm_base_url_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "kaggle_username", "user")
    monkeypatch.setattr(settings, "kaggle_key", "key")
    monkeypatch.setattr(settings, "kaggle_kernel_ref", "user/kernel")
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        await lifespan(app).__anext__()

def test_dev_allows_empty_llm_base_url(monkeypatch):
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(settings, "llm_base_url", "")
    # should not raise
    await lifespan(app).__anext__()
```

**Commit Message:** `feat(config): LLM_BASE_URL default empty; fail-fast on prod when enabled`

---

### 7. ENV Default Stays Dev; .env.example Prod Section Documented

**Files:**
- `deploy/.env.example` — add prod section with `ENV=prod` + comments

**Spec:**
- `Settings.env` default remains `"dev"` (no code change)
- `.env.example` adds a commented prod block:
  ```bash
  # --- Production ---
  # ENV=prod
  # APP_SECRET=<32+ random bytes>
  # RUNNER_KEY=<32+ random bytes>
  # ADMIN_EMAIL=admin@prod.example
  # ADMIN_PASSWORD=<strong>
  # LLM_BASE_URL=https://llm.example.com/v1
  # POSTGRES_PASSWORD=<strong>
  # ...other prod overrides...
  ```
- Fail-fast guards from tasks 1-3,6 already cover prod validation

**Test Criteria:**
- `grep -A 10 "Production" deploy/.env.example` shows the block

**Commit Message:** `docs(env): add prod section to .env.example with comments`

---

### 8. Nginx Security Headers + Healthz + Compose Healthcheck; TLS External

**Files:**
- `deploy/nginx.conf` — add security headers, verify `/healthz`
- `deploy/docker-compose.yml` — add healthcheck to nginx and server
- `server/app/routers/health.py` — ensure `/healthz` returns 200 (already exists per `test_health.py`)

**Spec:**
- nginx `server` block adds:
  ```nginx
  add_header X-Content-Type-Options nosniff;
  add_header X-Frame-Options DENY;
  add_header Referrer-Policy strict-origin-when-cross-origin;
  ```
- `/healthz` location already proxies to `http://server:8000/healthz`
- docker-compose.yml:
  - `server` service: add `healthcheck` (HTTP GET `http://localhost:8000/healthz`)
  - `nginx` service: add `healthcheck` (HTTP GET `http://localhost/healthz`)
- TLS: Document as out-of-scope for code; certbot/reverse proxy terminates TLS before nginx. Add comment in nginx.conf and README.

**Test Criteria:**
- `curl -I http://localhost/healthz` returns headers + 200
- `docker compose -f deploy/docker-compose.yml up -d && docker compose ps` shows healthy for server + nginx

**Commit Message:** `feat(nginx): security headers + healthchecks; TLS external doc`

---

## Review Focus (Uncovered Failure Modes)

1. **Secrets rotation**: No automated rotation; ops must regenerate `APP_SECRET`/`RUNNER_KEY` manually and restart.
2. **LLM_BASE_URL validation**: Only checked at startup; if LLM endpoint changes at runtime, no reload signal.
3. **Admin bootstrap idempotency**: Prod fail-fast only on first boot; if admin user deleted later, next restart recreates (by design).
4. **Postgres password in logs**: Compose may echo env vars; ensure `POSTGRES_PASSWORD` not logged.
5. **Healthcheck false positives**: nginx healthcheck passes even if upstream server unhealthy (separate check); consider `proxy_next_upstream` tuning.

---

## Architecture

- **Validation layer**: Fail-fast in `lifespan` (app startup) — single gate, no scattered checks.
- **Config source**: pydantic-settings reads `.env` / env vars; validators enforce prod rules.
- **Compose/Dockerfile**: Declarative infrastructure hardening; no code changes beyond COPY.
- **Nginx**: Static config; headers added once, no dynamic logic.

## Tech Stack

- FastAPI + pydantic-settings (config)
- Docker Compose (orchestration)
- nginx:alpine (reverse proxy)
- pytest + monkeypatch (fail-fast tests)

---

## Implementation Plan Reference

See `docs/superpowers/plans/2026-10-15-p0-deploy-hardening.md` for task-by-task execution plan with checkboxes.
