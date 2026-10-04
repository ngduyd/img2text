# Plan A — Server Foundation & Auth

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI server scaffold + Postgres schema + full auth (register/login/logout/refresh/password-reset) + request_logs/page_views middleware + rate limit + admin bootstrap + healthz.

**Architecture:** Async FastAPI + SQLAlchemy 2 async + asyncpg. JWT access (15m) + refresh (30d) in httpOnly cookies, refresh rotation with jti reuse detection. All tests run against real Postgres (docker compose service), httpx ASGI client, no sqlite.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, asyncpg, Alembic, passlib[bcrypt], PyJWT, pydantic-settings, pytest + pytest-asyncio + httpx.

**Spec:** `docs/superpowers/specs/2026-10-04-img2text-mvp-design.md` §4 (users/refresh_tokens/page_views/request_logs), §8 (auth API), §9 (limits), §11 (env).

**Depends on:** nothing (first plan). Plan B builds jobs table + worker endpoints on this app.

## Global Constraints

- Repo root: `img2text/`. Server code: `server/`. All paths in this plan relative to `img2text/`.
- Python ≥3.11. Postgres 16 via `deploy/docker-compose.test.yml` service `postgres-test` on port 5433, database `img2text_test`, user/pass `img2text/img2text`.
- Cookies: `access` JWT 15 min, `refresh` JWT 30 days, both httpOnly SameSite=Lax; Secure iff `BASE_URL` starts with https.
- bcrypt cost 12. JWT secret: env `APP_SECRET`. Issuer `img2text`.
- Endpoints exactly: `/api/auth/register|login|logout|me|password/forgot|password/reset`, `/healthz`.
- Register response: `201 {id, email, role, ocr_enabled}`; `role="user"`, `ocr_enabled=False`. Duplicate email → `409`.
- Forgot-password: always `202 {}` (no user enumeration); token hashed in DB, TTL 1h, single-use.
- Auth rate limit: 10 req/hour/IP on register+login+password/* → `4229`/`429`. In-process sliding window (`server/app/limiter.py`).
- `request_logs` middleware writes every request (method, path normalized (no query), status, user_id nullable, ip from `X-Forwarded-For` first value else client addr, ua). Retention 7 days via daily prune.
- `page_views` middleware: counts GET requests whose path does NOT start `/api/` and is not a static asset (`.js|.css|.png|.svg|.ico`), nullable user_id.
- Admin bootstrap: startup, if `ADMIN_EMAIL`+`ADMIN_PASSWORD` set and email absent → create `role="admin"`.
- TDD order mandatory: failing test → red → implement → green → commit. Never write implementation before its test.
- Commit per task. Commit messages: `feat(server): ...`, `test(server): ...`.

## Review Focus

- Cookie theft: refresh reuse must revoke the whole family, not just the token (test: reuse after rotation → all refresh invalid).
- User enumeration: forgot-password identical response/latency path for known and unknown emails (test: both 202, body identical).
- bcrypt verify on malformed hash must not raise (test: login with wrong password → 401, not 500).
- Rate limiter keyed by IP must not share state across users behind same IP with different paths (test: 10 logins + 1 me = me still 200).
- Prune must delete only old rows (test: rows older than 7d deleted, recent kept).

---

### Task 1: Scaffold + test harness + healthz

**Files:**
- Create: `server/pyproject.toml`, `server/app/__init__.py`, `server/app/main.py`, `server/app/config.py`, `server/app/db.py`, `server/app/routers/health.py`, `server/tests/__init__.py`, `server/tests/conftest.py`, `deploy/docker-compose.test.yml`, `server/pytest.ini`

**Interfaces:**
- Produces: `create_app() -> FastAPI` (used by every later test via `server/tests/conftest.py:client` fixture); `Settings` pydantic-settings reading env (`DATABASE_URL`, `APP_SECRET`, `BASE_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `LOG_PATH`, `SMTP_*`, `RUNNER_KEY`); `Base` (SQLAlchemy declarative); `get_session() -> AsyncIterator[AsyncSession]`.

- [ ] **Step 1: Write failing test** `server/tests/test_health.py`:

```python
async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True}
```

- [ ] **Step 2: Run → FAIL** (`cd server && pytest tests/test_health.py -v`, ModuleNotFoundError/ImportError)

- [ ] **Step 3: Implement** `pyproject.toml` deps as listed in stack; `config.py` `Settings(BaseSettings)` with `database_url="postgresql+asyncpg://img2text:img2text@localhost:5433/img2text_test"` default; `db.py` engine+session factory; `health.py` SELECT 1 via `get_session`, return `{"status":"ok","db":True}`, `503` on exception; `main.py` `create_app()` wiring router + `app.state.settings`. `docker-compose.test.yml`: postgres:16-alpine, ports 5433:5432, healthcheck `pg_isready`.

- [ ] **Step 4: Run → PASS** (`docker compose -f deploy/docker-compose.test.yml up -d --wait && cd server && pytest tests/test_health.py -v`)

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(server): scaffold, test harness, healthz"`

---

### Task 2: DB models + schema create

**Files:**
- Create: `server/app/models.py`, `server/tests/test_models.py`

**Interfaces:**
- Produces: `User(id:int, email:str unique, password_hash:str, role:str default "user", ocr_enabled:bool default False, created_at:datetime)`, `RefreshToken(id, user_id FK, jti:UUID unique, token_hash:str, expires_at:datetime, used_at:datetime|None)`, `PageView(id, path:str, user_id:FK nullable, created_at)`, `RequestLog(id, ts, method, path, status:int, user_id nullable, ip:str, ua:str|None)`, `Setting(key:str PK, value:str)`.

- [ ] **Step 1: Failing test** `server/tests/test_models.py`:

```python
async def test_create_user_and_refresh(db_session):
    u = User(email="a@b.c", password_hash="x")
    db_session.add(u); await db_session.flush()
    t = RefreshToken(user_id=u.id, jti=uuid4(), token_hash="h",
                     expires_at=datetime.now(timezone.utc))
    db_session.add(t); await db_session.flush()
    assert u.id and t.user_id == u.id
    s = Setting(key="usd_per_gpu_hour", value="0.0")
    db_session.add(s); await db_session.flush()
```

- [ ] **Step 2: Run → FAIL** (ImportError models)
- [ ] **Step 3: Implement** models per Interfaces; `Base.metadata.create_all` on app startup (Alembic added in Plan B once jobs table exists — ponytail: single create_all until schema stabilizes, upgrade to Alembic before first deploy).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(server): core models (users, refresh_tokens, page_views, request_logs, settings)`

---

### Task 3: Register + login + /me (JWT cookies)

**Files:**
- Create: `server/app/security.py`, `server/app/deps.py`, `server/app/routers/auth.py`, `server/tests/test_auth_register_login.py`
- Modify: `server/app/main.py`

**Interfaces:**
- Produces: `hash_password(p:str)->str`, `verify_password(p:str,h:str)->bool` (returns False on any exception, never raises), `create_access_token(sub:str, role:str)->str`, `create_refresh_token()->tuple[str,UUID]` (token, jti); `get_current_user(request, session)->User` (cookie `access`, raises 401); `require_admin(user)->User` (403 if role!="admin"); `require_ocr(user)->User` (403 if not ocr_enabled); `get_runner_key(request)->str` (Bearer `RUNNER_KEY`, 401 mismatch) — last one used by Plan B.

- [ ] **Step 1: Failing tests** `server/tests/test_auth_register_login.py`:

```python
async def test_register_201_and_me(client):
    r = await client.post("/api/auth/register", json={"email":"u@x.io","password":"secret123"})
    assert r.status_code == 201
    body = r.json(); assert body["role"] == "user" and body["ocr_enabled"] is False
    r2 = await client.get("/api/auth/me")
    assert r2.status_code == 200 and r2.json()["email"] == "u@x.io"

async def test_register_duplicate_409(client):
    await client.post("/api/auth/register", json={"email":"d@x.io","password":"secret123"})
    r = await client.post("/api/auth/register", json={"email":"d@x.io","password":"secret123"})
    assert r.status_code == 409

async def test_login_wrong_password_401_not_500(client):
    await client.post("/api/auth/register", json={"email":"w@x.io","password":"secret123"})
    r = await client.post("/api/auth/login", json={"email":"w@x.io","password":"wrong-pass"})
    assert r.status_code == 401

async def test_me_without_cookie_401(client):
    assert (await client.get("/api/auth/me")).status_code == 401
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** security.py + deps.py + auth router per Interfaces. Register: validate email format + password ≥8 chars (422 otherwise), bcrypt hash, insert, set `access` cookie, 201. Login: verify, 401 on mismatch, set `access` cookie. Me: decode cookie → user JSON. Cookie helper in `security.py`: `set_auth_cookies(response, access, refresh)`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(server): register/login/me with JWT access cookie`

---

### Task 4: Refresh rotation + reuse detection + logout

**Files:**
- Create: `server/tests/test_auth_refresh.py`
- Modify: `server/app/routers/auth.py`

**Interfaces:**
- Produces: `POST /api/auth/refresh` → rotates: marks old used_at, inserts new, sets both cookies, 200 `{}`. Reuse (jti already used_at set) → delete ALL refresh_tokens for user, 401. `POST /api/auth/logout` → revoke all user refresh tokens, clear cookies, 200.

- [ ] **Step 1: Failing tests**:

```python
async def _register_login(client):
    await client.post("/api/auth/register", json={"email":"r@x.io","password":"secret123"})
    await client.post("/api/auth/login", json={"email":"r@x.io","password":"secret123"})

async def test_refresh_rotates(client):
    await _register_login(client)
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200 and "refresh" in r.cookies

async def test_refresh_reuse_revokes_family(client):
    await _register_login(client)
    stolen = client.cookies.get("refresh")
    await client.post("/api/auth/refresh")          # rotate: stolen now used
    r = await client.post("/api/auth/refresh")      # reuse → 401
    assert r.status_code == 401
    client.cookies.set("refresh", stolen)
    assert (await client.post("/api/auth/refresh")).status_code == 401  # stolen dead too

async def test_logout_revokes(client):
    await _register_login(client)
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 401
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** refresh/logout in auth.py per Interfaces. Refresh token JWT: sub=user_id, jti, exp=30d; store sha256(token) in `token_hash`.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): refresh rotation, reuse detection, logout`

---

### Task 5: Password forgot/reset + SMTP

**Files:**
- Create: `server/app/mailer.py`, `server/tests/test_auth_password_reset.py`
- Modify: `server/app/routers/auth.py`

**Interfaces:**
- Produces: `send_email(to:str, subject:str, body:str)->None` (smtplib sync, run via `anyio.to_thread`; SMTP_* env; on failure logs, never 500 the request); `POST /api/auth/password/forgot {email}` → 202 `{}` always (identical body known/unknown email), if user exists insert reset token (hashed, exp 1h) + send link `{BASE_URL}/reset?token=...`; `POST /api/auth/password/reset {token, password}` → 200, consumes token (single-use), rehashes password, revokes all refresh tokens; invalid/expired token → 422.

- [ ] **Step 1: Failing tests** (SMTP monkeypatched to capture):

```python
async def test_forgot_identical_response(client, monkeypatch):
    sent = []
    monkeypatch.setattr("app.mailer.send_email", lambda to, s, b: sent.append(to))
    await client.post("/api/auth/register", json={"email":"p@x.io","password":"secret123"})
    r1 = await client.post("/api/auth/password/forgot", json={"email":"p@x.io"})
    r2 = await client.post("/api/auth/password/forgot", json={"email":"nobody@x.io"})
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json()
    assert sent == ["p@x.io"]

async def test_reset_changes_password_and_revokes(client, monkeypatch):
    monkeypatch.setattr("app.mailer.send_email", lambda *a: None)
    await client.post("/api/auth/register", json={"email":"q@x.io","password":"secret123"})
    await client.post("/api/auth/password/forgot", json={"email":"q@x.io"})
    # extract token from DB (test reads reset table directly)
    r = await client.post("/api/auth/password/reset", json={"token": TEST_LAST_TOKEN, "password":"newsecret1"})
    assert r.status_code == 200
    assert (await client.post("/api/auth/login", json={"email":"q@x.io","password":"newsecret1"})).status_code == 200
    assert (await client.post("/api/auth/login", json={"email":"q@x.io","password":"secret123"})).status_code == 401

async def test_reset_invalid_token_422(client):
    assert (await client.post("/api/auth/password/reset", json={"token":"nope","password":"newsecret1"})).status_code == 422
```

(`TEST_LAST_TOKEN`: conftest helper `capture_reset_token(db_session)` returns last raw token — store raw token in a transient column `token_raw`? No: store raw token hashed; test monkeypatches `security.hash_token` to echo so it can read DB. Choose: `token_hash = sha256(token)`; test computes token itself via same generator used in route → factor `generate_reset_token() -> str` in security.py so test and route share it.)

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** mailer.py + routes + `PasswordResetToken` table (or reuse `Setting`? No — new table `password_reset_tokens(id, user_id, token_hash, expires_at, used_at)` added in models.py) per Interfaces.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): password reset via SMTP`

---

### Task 6: Auth rate limiter

**Files:**
- Create: `server/app/limiter.py`, `server/tests/test_rate_limit.py`
- Modify: `server/app/routers/auth.py`

**Interfaces:**
- Produces: `SlidingWindow(limit:int, window_seconds:int)` with `.check(key:str)->bool`; FastAPI dependency `rate_limit_auth(request)` — key = client IP, limit 10/3600s, applied to register+login+password/forgot. In-process dict with lazy eviction. ponytail: single-process only; multi-worker deploy → move to Postgres before scale.

- [ ] **Step 1: Failing test**:

```python
async def test_login_rate_limit_429(client):
    for _ in range(10):
        await client.post("/api/auth/login", json={"email":"x@y.z","password":"secret123"})
    r = await client.post("/api/auth/login", json={"email":"x@y.z","password":"secret123"})
    assert r.status_code == 429

async def test_me_not_limited_same_ip(client):
    for _ in range(10):
        await client.post("/api/auth/login", json={"email":"x@y.z","password":"secret123"})
    assert (await client.get("/api/auth/me")).status_code == 401  # limiter only on auth POSTs
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces. Test client sets X-Forwarded-For to simulate distinct IPs in other tests if needed.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): sliding-window rate limit on auth endpoints`

---

### Task 7: request_logs + page_views middleware + prunes

**Files:**
- Create: `server/app/middleware.py`, `server/tests/test_logging_middleware.py`
- Modify: `server/app/main.py`

**Interfaces:**
- Produces: two pure-ASGI middlewares; `prune_request_logs(session, days=7)->int`, `prune_page_views(session, days=90)->int`, `prune_refresh_tokens(session)->int` (expired only) — called by APScheduler in Task 8. Path normalization: strip query string; cap path length 512.

- [ ] **Step 1: Failing tests**:

```python
async def test_request_logged(client, db_session):
    await client.post("/api/auth/register", json={"email":"m@x.io","password":"secret123"})
    rows = (await db_session.execute(select(RequestLog))).scalars().all()
    assert any(r.path == "/api/auth/register" and r.status == 201 for r in rows)

async def test_page_view_logged_and_api_excluded(client, db_session):
    await client.get("/")                      # SPA route → 1 page_view
    await client.get("/api/auth/me")           # api → 0 page_views
    pvs = (await db_session.execute(select(PageView))).scalars().all()
    assert sum(1 for p in pvs if p.path == "/") == 1
    assert not any(p.path.startswith("/api") for p in pvs)

async def test_prune_deletes_only_old(db_session):
    db_session.add(RequestLog(method="GET", path="/x", status=200, ip="1.1.1.1",
                              ts=datetime.now(timezone.utc)-timedelta(days=8)))
    db_session.add(RequestLog(method="GET", path="/y", status=200, ip="1.1.1.1"))
    await db_session.flush()
    n = await prune_request_logs(db_session)
    assert n == 1
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** middleware.py + register in create_app (order: request_logs outermost) per Interfaces.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): request_logs/page_views middleware + prune helpers`

---

### Task 8: APScheduler + admin bootstrap + admin dep test

**Files:**
- Create: `server/app/scheduler.py`, `server/tests/test_admin_bootstrap.py`
- Modify: `server/app/main.py`

**Interfaces:**
- Produces: `init_scheduler(app)` — jobs every 1m: lease reaper placeholder (no-op until Plan B fills `reap_leases` import — import from `app.jobs_requeue` if present, skip if ImportError), daily 03:00: three prunes. Startup hook: `bootstrap_admin(session, email, password)`.

- [ ] **Step 1: Failing tests**:

```python
async def test_bootstrap_admin_creates(db_session, monkeypatch):
    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")
    u = (await db_session.execute(select(User).where(User.email=="admin@x.io"))).scalar_one()
    assert u.role == "admin"
    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")   # idempotent
    assert (await db_session.execute(select(User).where(User.email=="admin@x.io"))).scalars().all().__len__() == 1

async def test_admin_dep_403_for_user(client):
    await client.post("/api/auth/register", json={"email":"n@x.io","password":"secret123"})
    # hit a dummy admin-only route defined in test app
    assert (await client.get("/api/admin/__probe")).status_code == 403
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** scheduler.py + `bootstrap_admin` + wire startup + temporary `GET /api/admin/__probe` route using `require_admin` (kept — real admin routes come in Plan E).
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): scheduler, admin bootstrap, admin dependency`

---

**Plan A done when:** all tests green with `docker compose -f deploy/docker-compose.test.yml up -d --wait && cd server && pytest -v`, git history linear on worktree branch `plan-a-server-foundation`.
