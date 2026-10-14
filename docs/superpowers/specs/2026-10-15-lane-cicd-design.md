# Spec: Lane CICD — GitHub Actions CI + CD push Docker Hub (2026-10-15)

Base: master `4545df3`. GitHub `ngduyd/img2text`.
User ruling: **CD = build docker image + push Docker Hub THÔI** (không deploy, không registry khác).

## CD scope (option b — cả 2 image)

| Image | Source | Tag |
|---|---|---|
| `<dockerhub_user>/img2text-server` | `deploy/Dockerfile` (python 3.11-slim, `pip install server[kaggle]`) | `:<version từ tag>` + `latest` |
| `<dockerhub_user>/img2text-web` | **Dockerfile mới** `web/Dockerfile` (build stage `npm ci && npx vite build` → `nginx:alpine` serve `dist`) | `:<version từ tag>` + `latest` |

## CI (mọi PR + push `master`)

- **server**: job postgres:16-alpine service (user/pass `img2text`, db `img2text_test`),
  `pip install -e ".[dev]"`, apply migrations (docs/migrations/*.sql), `pytest -q`.
  Env `DATABASE_URL=postgresql+asyncpg://img2text:img2text@postgres:5436/img2text_test` (port service).
- **web**: `npm ci`, `npx tsc -b --force`, `npx vitest run`, `npx vite build`.
- Cả 2 job phải pass mới chạy CD job.

## CD (chỉ khi push **git tag `v*`** — mỗi tag = 1 version)

- Trigger: `on: push: tags: ['v*']` (+ `workflow_dispatch`).
- Mỗi lần bạn đánh tag `v1.2.0` + push tag → build 2 image + push với tag
  `v1.2.0` (đúng version) + `latest`. **Commit lẻ lên master KHÔNG trigger CD**
  (chỉ CI).

- Job `docker` (needs: [server, web]):
  - `docker/login-action` với secrets `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`
  - `docker/build-push-action` ×2 (server + web), push=true,
    tags: `<user>/img2text-server:${{ github.ref_name }}` (tag v1.2.0) + `:latest` (web tương tự),
    cache: `type=gha` (cache layer build nhanh).
  - **KHÔNG** deploy, không notify, không registry khác.
- Manual: `workflow_dispatch` (chạy CD tùy ý từ UI, version tag = tên run).

## Non-goals
- Không auto-deploy lên VPS/server nào.
- Không multi-arch (amd64 only — hiện tại).
- Không tag `sha-*` — chỉ version từ git tag + latest.

## Hand steps (user)
1. Tạo Personal Access Token Docker Hub → GitHub repo secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.
2. (Lần đầu) `docker pull` verify sau push.
