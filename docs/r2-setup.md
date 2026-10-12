# R2 — bucket setup

Storage is Cloudflare R2 only (S3-compatible, boto3 presigned URLs). Any S3
endpoint works via env change (MinIO, B2). Worker and browser never need R2
credentials — the server mints short-TTL presigned GETs.

## 1. Create the bucket

Cloudflare dashboard → R2 → Create bucket. Name: `img2text` (or match
`R2_BUCKET`). Location: automatic. **Public access off** — presigned URLs need
no public bucket.

## 2. API token

Dashboard → My Profile → API Tokens → Create Token → Custom permissions:

- **Object Read & Write**, scoped to the `img2text` bucket
  (Token permissions: R2 → Object Read & Write; TTL as you prefer).

Save the generated **Access Key ID** and **Secret Access Key**.

## 3. Lifecycle rules (dashboard, no code)

Bucket → Settings → Lifecycle rules. Prefix-based, per spec §5:

| Prefix   | Rule                        | Why                                              |
|----------|-----------------------------|--------------------------------------------------|
| `uploads/` | Delete after **30 days**  | content-addressed originals; result JSONB in Postgres loses nothing essential |
| `exports/` | Delete after **7 days**   | regenerable on demand, cached per format          |
| `crops/`   | **No rule — keep forever** | small; preview issues panel depends on them       |

Key layout written by the server:

```
uploads/{sha256}.{ext}          content-addressed, immutable, dedup by hash
crops/{job_id}/{region_id}.jpg  lazy-generated, cached
exports/{job_id}/{fmt}          lazy-generated, cached
```

## 4. Fill `.env`

Endpoint format: `https://<account>.r2.cloudflarestorage.com` — the
`<account>` subdomain is shown in the dashboard (bucket → Overview → S3 API).

```
R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<from token>
R2_SECRET_ACCESS_KEY=<from token>
R2_BUCKET=img2text
R2_REGION=auto
R2_PUBLIC_BASE=            # optional; reserved for public CDN domain later
```

`server/tests/test_env_parity.py` fails if keys drift from `Settings` fields.

## Presigned URLs — no public bucket

Uploads go browser → R2 directly via presigned PUT; previews, worker
downloads, crops and
exports are served via presigned GETs (TTLs: worker download 1 h, original
preview 1 h, crops 24 h, exports 24 h). The bucket stays private.

## Presigned PUT — CORS

R2 không implement Presigned POST (HTTP 501) → client chuyển sang presigned
PUT upload thẳng từ browser. Browser preflight OPTIONS trước PUT, nên bucket
cần CORS policy (R2 → bucket → Settings → CORS policy):

| Setting        | Value                                                  |
|----------------|--------------------------------------------------------|
| AllowedOrigins | `http://localhost:5173` + prod domain (VD `https://…`) |
| AllowedMethods | `PUT, GET, HEAD, OPTIONS`                              |
| AllowedHeaders | `*`                                                    |
| MaxAge         | `600` (cache preflight, giảm OPTIONS round-trip)       |

Thiếu CORS → browser block upload dù URL presigned còn hạn. `OPTIONS` cần
trong AllowedMethods vì chính preflight là một request OPTIONS.

## Rebuild deploy/reference.docx

`deploy/reference.docx` is a committed artifact used as pandoc's
`--reference-doc` for DOCX export. After any change to
`deploy/make_reference_docx.py`, rebuild and commit the artifact:

```bash
python deploy/make_reference_docx.py deploy/reference.docx
```

`server/tests/test_reference_rebuild.py` fails if the committed artifact
drifts from the builder's output.
