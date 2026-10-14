# Spec: Lane CICD — GitHub Actions CI + CD push Docker Hub (2026-10-15)

Base: master `4545df3`. GitHub `ngduyd/img2text`.
User ruling: **CD = build docker image + push Docker Hub THÔI** (không deploy, không registry khác).

## CD scope (option b — cả 2 image)

| Image | Source | Tag |
|---|---|---|
| `<dockerhub_user>/img2text-server` | `deploy/Dockerfile` (python 3.11-slim, `pip install server[kaggle]`) | `latest` + `sha-<short>` |
| `<dockerhub_user>/img2text-web` | **Dockerfile mới** `web/Dockerfile` (build stage `npm ci && npx vite build` → `nginx:alpine` serve `dist`) | `latest` + `sha-<short>` |

## CI (mọi PR + push `main`)

- **server**: job postgres:16-alpine service (user/pass `img2text`, db `img2text_test`),
  `pip install -e "./server[test]"` (pyproject extra = `test`, KHÔNG có `dev`), apply migrations (docs/migrations/*.sql), `pytest -q`.
  Env `DATABASE_URL=...@localhost:5436/...` (GH runner: services map qua localhost — KHÔNG phải hostname `postgres`).
- **web**: `npm ci`, `npx tsc -b --force`, `npx vitest run`, `npx vite build`.
- Cả 2 job phải pass mới chạy CD job.

## CD (chỉ khi push vào `main`, sau CI pass)

- Job `docker` (needs: [server, web]):
  - `docker/login-action` với secrets `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`
  - `docker/build-push-action` ×2 (server + web), push=true,
    tags: `<user>/img2text-server:latest` + `:sha-${{ github.sha }}` (short 7),
    cache: `type=gha` (cache layer build nhanh).
  - **KHÔNG** deploy, không通知, không registry khác.
- Manual: `workflow_dispatch` (chạy CD tùy ý từ UI).

## Non-goals
- Không auto-deploy lên VPS/server nào.
- Không multi-arch (amd64 only — hiện tại).
- Không release/tag semver (chỉ `latest` + sha).

## Hand steps (user)
1. Tạo Personal Access Token Docker Hub → GitHub repo secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.
2. (Lần đầu) `docker pull` verify sau push.
