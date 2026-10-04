# Plan D — Editing, Crops, Export (md/html/docx/pdf)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Inline editing (`edited_markdown`), lazy region crops, export to md/html/docx/pdf via pandoc + weasyprint with `deploy/reference.docx`, crop embedding in exports, R2 export caching with invalidation on edit.

**Architecture:** Server-side generation (i5 handles pandoc fine — sync, 60 s timeout). Canonical markdown = `result.edited_markdown` if present else `result.markdown`. Exports cached to `exports/{job_id}/{fmt}` in R2; presigned GET 24 h. Edit invalidates the prefix. Crops generated once from the R2 original via PIL, cached to `crops/{job_id}/{region_id}.jpg`.

**Tech Stack:** Plan B stack + `pandoc` (binary), `weasyprint`, `python-docx` (reference builder), `Pillow`.

**Spec:** §5 (storage keys/TTLs), §8 (`PATCH content`, `export`, `regions/{rid}/crop`), §9 (export generation), §10 (editing & DOCX fidelity), §11 repo `deploy/reference.docx`.

**Depends on:** Plan B (jobs router, storage driver, VALID_RESULT_JSONB), Plan A (auth deps).

## Global Constraints

- `PATCH /api/jobs/{id}/content {markdown}`: owner, `status=done` only (else 409), `markdown` non-empty str ≤2 MB (else 422); stores into `result.edited_markdown`; calls `storage.delete_prefix(f"exports/{job_id}/")`; returns `200 {}`.
- `POST /api/jobs/{id}/export {fmt}`: fmt ∈ `md|html|docx|pdf`; owner; job must be `done` (else 409); returns `{"url"}` presigned 86400s. Cache: `exists(exports/{id}/{fmt})` → presign only; else generate → `put` → presign.
- Crop: `GET /api/jobs/{id}/regions/{rid}/crop` → `{"url"}` presigned 86400s; bbox required (else 404); generated from original via PIL: crop bbox, resize width ≤800, JPEG q70; cached `crops/{id}/{rid}.jpg`.
- Marker→image rewrite (all formats): region verdict `image_unextractable` with bbox → replace exact marker `**[Hình ảnh chưa trích xuất: vùng {rid}]**` with `![vùng {rid}](crops/{rid}.jpg)`; materialize crop files into tempdir before pandoc; `bbox: null` regions keep marker text.
- Export source text: `edited_markdown or markdown` — never the raw `pages[]`.
- pandoc flags: `--reference-doc=deploy/reference.docx` for docx; `--standalone` for html; pdf = md→html standalone → weasyprint `HTML(string=..., base_url=tempdir).write_pdf()`.
- reference.docx builder: `deploy/make_reference_docx.py` (python-docx) creating styles `Normal` (Calibri 11), `Heading 1/2/3`, `Table Grid`; committed output at `deploy/reference.docx`.
- i18n: export error → `500 {"detail":"Xuất file thất bại."}` (sanitized); test asserts no stack trace in body.
- TDD per task; tests use moto storage + real pandoc/weasyprint (CI installs both — see Plan G).

## Review Focus

- Editing while job not done must not corrupt result (409 test).
- Export cache must serve stale-free content after edit (edit → export → bytes differ — test).
- Crop bbox coordinates are absolute page pixels (test with known-color image, assert output pixel colors).
- Marker rewrite must not fire for `bbox: null` (test: marker survives in md export).
- weasyprint HTML injection: sanitized markdown required BEFORE export — assert DOMPurify-sanitized output passed (test with `<script>` in markdown → docx/pdf bytes contain no `<script>`).

---

### Task 1: `PATCH content` + export endpoint skeleton (md only)

**Files:**
- Create: `server/app/routers/exports.py`, `server/tests/test_edit_content.py`, `server/tests/test_export_md.py`
- Modify: `server/app/main.py`

**Interfaces:**
- Consumes: Plan B `Job`, `get_storage()`, schemas.
- Produces: `PATCH /api/jobs/{id}/content` per Global Constraints; `POST /api/jobs/{id}/export` handling `fmt="md"` (full cache flow); helper `current_markdown(result: dict) -> str`.

- [ ] **Step 1: Failing tests** `server/tests/test_edit_content.py`:

```python
async def test_patch_content_done(auth_client, done_job_with_result):
    r = await auth_client.patch(f"/api/jobs/{done_job_with_result}/content",
                                json={"markdown": "## Part 2\nEdited."})
    assert r.status_code == 200
    job = await db_session.get(Job, done_job_with_result)
    assert job.result["edited_markdown"] == "## Part 2\nEdited."

async def test_patch_content_409_when_queued(auth_client, seed_job):
    r = await auth_client.patch(f"/api/jobs/{seed_job}/content", json={"markdown": "x"})
    assert r.status_code == 409

async def test_patch_content_422_empty(auth_client, done_job_with_result):
    r = await auth_client.patch(f"/api/jobs/{done_job_with_result}/content", json={"markdown": ""})
    assert r.status_code == 422

async def test_patch_invalidates_export_cache(auth_client, done_job_with_result, storage_spy):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    await auth_client.patch(f"/api/jobs/{done_job_with_result}/content", json={"markdown": "new"})
    storage_spy.delete_prefix.assert_any_call(f"exports/{done_job_with_result}/")
```

`server/tests/test_export_md.py`:

```python
async def test_export_md_returns_presigned_and_caches(auth_client, done_job_with_result, storage_spy):
    r1 = await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    assert r1.status_code == 200 and "exports/" in r1.json()["url"]
    calls_after_first = storage_spy.put.call_count
    r2 = await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    assert r2.status_code == 200 and storage_spy.put.call_count == calls_after_first  # cache hit

async def test_export_uses_edited_markdown(auth_client, done_job_with_result, storage):
    await auth_client.patch(f"/api/jobs/{done_job_with_result}/content", json={"markdown": "# EDITED"})
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    body = await storage.get(f"exports/{done_job_with_result}/md")
    assert body == b"# EDITED"

async def test_export_409_when_not_done(auth_client, seed_job):
    r = await auth_client.post(f"/api/jobs/{seed_job}/export", json={"fmt": "md"})
    assert r.status_code == 409
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces (md branch only; other fmts → 501 `{"detail":"Chưa hỗ trợ."}` for now — removed task-by-task below). Add `StorageDriver.get(key)->bytes` to Plan B driver if missing.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): edit content + md export with cache`

---

### Task 2: Lazy crops

**Files:**
- Create: `server/tests/test_crop.py`
- Modify: `server/app/routers/exports.py`

**Interfaces:**
- Produces: `GET /api/jobs/{id}/regions/{rid}/crop` per Global Constraints; helper `get_or_make_crop(job_id, rid) -> str` (returns storage key).

- [ ] **Step 1: Failing tests** (original = 200×400 image: left half red, right half blue; region bbox [100, 50, 200, 150]):

```python
async def test_crop_generated_and_cached(auth_client, done_job_with_bbox, storage_spy, storage):
    r = await auth_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p1r0/crop")
    assert r.status_code == 200 and "crops/" in r.json()["url"]
    n = storage_spy.put.call_count
    await auth_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p1r0/crop")  # cache hit
    assert storage_spy.put.call_count == n
    img = Image.open(io.BytesIO(await storage.get(f"crops/{done_job_with_bbox}/p1r0.jpg")))
    assert img.width == 100 and 95 <= img.height <= 105          # resized ≤800, bbox size

async def test_crop_404_no_bbox(auth_client, done_job_with_null_bbox):
    r = await auth_client.get(f"/api/jobs/{done_job_with_null_bbox}/regions/p1r0/crop")
    assert r.status_code == 404

async def test_crop_404_unknown_region(auth_client, done_job_with_bbox):
    r = await auth_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p9r9/crop")
    assert r.status_code == 404

async def test_crop_owner_only(auth_client, other_client, done_job_with_bbox):
    assert (await other_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p1r0/crop")).status_code == 403
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces: find region in `result["pages"][*]["regions"]` by id; `storage.get(job.storage_key)` → PIL open → crop → resize `(w*800//w)` if width>800 → save JPEG q70 to BytesIO → `put`.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): lazy region crops`

---

### Task 3: html + docx export (pandoc + reference.docx)

**Files:**
- Create: `deploy/make_reference_docx.py`, `deploy/reference.docx` (committed artifact), `server/tests/test_export_docx.py`, `server/tests/test_reference.py`
- Modify: `server/app/routers/exports.py`

**Interfaces:**
- Produces: `make_reference_docx(path: str) -> None`; export fmt `html` → pandoc standalone; fmt `docx` → pandoc `--reference-doc=deploy/reference.docx`; shared `_materialize_crops(job, markdown, tempdir) -> str` (marker→image rewrite per Global Constraints, returns rewritten markdown).

- [ ] **Step 1: Failing tests** `server/tests/test_reference.py`:

```python
def test_reference_docx_has_styles(tmp_path):
    p = tmp_path / "ref.docx"; make_reference_docx(str(p))
    doc = Document(str(p))
    names = {s.name for s in doc.styles}
    assert {"Normal", "Heading 1", "Heading 2", "Heading 3", "Table Grid"} <= names
```

`server/tests/test_export_docx.py`:

```python
async def test_export_docx_bytes_valid(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx"})
    body = await storage.get(f"exports/{done_job_with_result}/docx")
    assert body[:2] == b"PK"                                    # zip container
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert "word/document.xml" in z.namelist()

async def test_export_html_contains_heading(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "html"})
    body = (await storage.get(f"exports/{done_job_with_result}/html")).decode()
    assert "<h2" in body

async def test_export_uses_reference_styles(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx"})
    body = await storage.get(f"exports/{done_job_with_result}/docx")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        styles = z.read("word/styles.xml").decode()
    assert "Heading1" in styles and "Calibri" in styles          # reference.docx applied
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** `make_reference_docx.py` (python-docx: Normal font Calibri 11; Heading 1/2/3 fonts; Table Grid style ensure present); run once, commit `deploy/reference.docx`; export branches html/docx via `subprocess.run(["pandoc", ...], capture_output=True, timeout=55)`; non-zero → sanitized 500 per Global Constraints.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): html/docx export with reference styles`

---

### Task 4: pdf export + marker→image rewrite + script sanitization

**Files:**
- Create: `server/tests/test_export_pdf_rewrite.py`
- Modify: `server/app/routers/exports.py`

**Interfaces:**
- Produces: fmt `pdf` branch (pandoc html → weasyprint); `_materialize_crops` fully active (replacing placeholder from Task 3); pre-export sanitization: markdown rendered through `markdown→sanitize (nháp nháp: bleach)` — MVP choice: HTML-sanitize AFTER pandoc html step for pdf, and for docx pandoc's own parser on our markdown (markdown itself cannot carry active script; test pins `<script>` literal text stays inert text, never executable).

- [ ] **Step 1: Failing tests**:

```python
async def test_export_pdf_magic(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "pdf"})
    body = await storage.get(f"exports/{done_job_with_result}/pdf")
    assert body[:4] == b"%PDF"

async def test_image_regions_embedded_in_exports(auth_client, done_job_with_marker_and_crop, storage):
    # result has image_unextractable region p1r0 with bbox + crop already in R2
    await auth_client.post(f"/api/jobs/{done_job_with_marker_and_crop}/export", json={"fmt": "md"})
    md = (await storage.get(f"exports/{done_job_with_marker_and_crop}/md")).decode()
    assert "![vùng p1r0](crops/p1r0.jpg)" in md
    assert "**[Hình ảnh chưa trích xuất: vùng p1r0]**" not in md
    await auth_client.post(f"/api/jobs/{done_job_with_marker_and_crop}/export", json={"fmt": "docx"})
    body = await storage.get(f"exports/{done_job_with_marker_and_crop}/docx")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert any(n.startswith("word/media/") for n in z.namelist())

async def test_null_bbox_keeps_marker(auth_client, done_job_with_null_bbox_marker, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_null_bbox_marker}/export", json={"fmt": "md"})
    md = (await storage.get(f"exports/{done_job_with_null_bbox_marker}/md")).decode()
    assert "**[Hình ảnh chưa trích xuất: vùng p1r1]**" in md

async def test_script_in_markdown_not_executable_in_html(auth_client, done_job_with_xss, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_xss}/export", json={"fmt": "html"})
    body = (await storage.get(f"exports/{done_job_with_xss}/html")).decode()
    assert "<script>alert(1)</script>" not in body
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** pdf branch + `_materialize_crops` active + html sanitize (pandoc html piped through `nhapl` — use `bleach.clean` with allowlist tags from pandoc output; add `bleach` dep) for html/pdf paths.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): pdf export, crop embedding, html sanitization`

---

**Plan D done when:** `pytest tests/test_edit_content.py tests/test_export_md.py tests/test_crop.py tests/test_export_docx.py tests/test_reference.py tests/test_export_pdf_rewrite.py -v` green with pandoc+weasyprint installed.
