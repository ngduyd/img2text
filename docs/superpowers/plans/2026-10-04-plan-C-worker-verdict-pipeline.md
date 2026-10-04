# Plan C — Worker: Verdict Logic, Pre-check, Pipeline, Colab Notebook

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Pure-Python worker core — image pre-check, VLM verdict resolution (dual-source-ready), `res.json` adapter → result JSONB, run-job loop against Plan B endpoints, Colab notebook wrapper.

**Architecture:** `worker/verdict.py` + `worker/pipeline.py` are importable modules with zero Colab dependencies; the notebook is a thin config+loop wrapper. Worker talks only to `GET /jobs/next`, `POST /jobs/{id}/heartbeat|result|fail` with Bearer tokens. Tests: standalone pytest under `worker/tests/` (no DB, no server import).

**Tech Stack:** Python 3.11+, numpy, opencv-python-headless, Pillow, rapidfuzz, httpx, pytest.

**Spec:** §7 worker pipeline, verdict table, structure fidelity; §4 result JSONB schema; §6 worker endpoints.

**Depends on:** Plan B (endpoints + `VALID_RESULT_JSONB` shape). Import `worker/verdict.py` from server tests later (spec §13) — keep modules dependency-light (no paddle imports).

## Global Constraints

- Pre-check thresholds (spec §7): Laplacian variance `< 100` → `blurry`; image width `< 1000 px` → `too_small`. Both true → skip VLM, `page_flag="unreadable"`. Exactly one true → run VLM, `page_flag="low_confidence"`. Neither → `page_flag="ok"`. Glyph-height check = ponytail: upgrade path in comment, not implemented.
- Verdicts emitted by MVP: `ok|image_unextractable|unreadable|low_confidence`. `ocr_preferred|vlm_lowconf` reserved (dual-source branch implemented + tested, unreachable with `sources={"vlm"}` only).
- Region id format: `p{page_index}r{region_index}` (1-based page, 0-based region).
- Warning marker text (exact): `**[Hình ảnh chưa trích xuất: vùng {region_id}]**`.
- Structure mapping (spec §7 fidelity): layout `title` → markdown `##`, `text` → paragraph verbatim, `table` → markdown table pipes preserved, region order = layout list order. Question numbering/options copied verbatim — never rewritten.
- VLM adapter assumption (verify in Task 5 smoke): `res.json = {"layout": [{"type": "text|image|table|title", "bbox": [x1,y1,x2,y2], "rec_texts": [...], "rec_scores": [...]}], "markdown": "<page md>"}`. Adapter isolated in `res_json_to_regions()` — shape fix is one function.
- `run_job` loop: backoff 5–30 s on 204; `401` on `/next` → raise `RunnerAuthError` (loop stops, visible); heartbeat per page boundary; `result` 409/422 → treat as failure, POST `fail` with error class; processing exception → POST `fail` (error ≤500 chars) then continue loop.
- `gpu_seconds`: `time.monotonic()` delta summed around `pipeline.predict` calls only.
- TDD per task; commit per task; worker tests run: `cd worker && pip install -e ".[test]" && pytest -v`.

## Review Focus

- `res.json` shape drift vs real Colab output (Task 5 manual smoke; adapter single-function blast radius).
- `resolve()` order: image region on unreadable page must stay `image_unextractable` (user must handle image regardless) — pinned by test.
- Similarity normalization must not crash on empty strings (empty vs empty → `ok` only if page ok; test).
- run_job must never POST `result` without prior heartbeat on last page (test asserts heartbeat count == page count).
- 401 stop must NOT be swallowed into `fail` (test asserts no fail POST on auth error).

---

### Task 1: `verdict.precheck`

**Files:**
- Create: `worker/pyproject.toml`, `worker/verdict.py`, `worker/tests/test_verdict_precheck.py`

**Interfaces:**
- Produces: `PrecheckResult(blurry: bool, too_small: bool)`; `precheck(img: np.ndarray) -> PrecheckResult` (grayscale internally; accepts BGR/gray; raises on empty array).

- [ ] **Step 1: Failing test** (synthetic images via PIL):

```python
def _page(width=1600, text=True):
    img = Image.new("L", (width, 2200), 255)
    if text:  # sharp black text → high Laplacian variance
        d = ImageDraw.Draw(img)
        for i in range(40):
            d.text((60, 40 + i * 50), f"Question {i+1}. Choose the best answer.", fill=0)
    return np.array(img)

def test_sharp_large_ok():
    r = precheck(_page())
    assert r.blurry is False and r.too_small is False

def test_blurry_detected():
    img = cv2.GaussianBlur(_page(), (31, 31), 0)   # kills variance
    r = precheck(img)
    assert r.blurry is True

def test_narrow_page_too_small():
    r = precheck(_page(width=800))
    assert r.too_small is True

def test_blank_page_is_blurry():
    r = precheck(_page(text=False))
    assert r.blurry is True
```

- [ ] **Step 2: Run → FAIL** (`cd worker && pytest tests/test_verdict_precheck.py -v`)
- [ ] **Step 3: Implement** `precheck` per Interfaces: `cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if 3ch else img, cv2.CV_64F).var() < 100 → blurry`; `img.shape[1] < 1000 → too_small`. ponytail comment for glyph-height upgrade.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(worker): image quality precheck`

---

### Task 2: `verdict.resolve` + normalization

**Files:**
- Create: `worker/tests/test_verdict_resolve.py`
- Modify: `worker/verdict.py`

**Interfaces:**
- Produces: `SourceResult(text: str, confidence: float | None)`; `Region(id: str, bbox: tuple[int,int,int,int] | None, sources: dict[str, SourceResult], is_image: bool = False)`; `normalize(text: str) -> str`; `similarity(a: str, b: str) -> float` (0–1, rapidfuzz); `resolve(region: Region, page_flag: str) -> str`.

Resolution order (pinned):
1. `region.is_image` → `image_unextractable`
2. `page_flag == "unreadable"` → `unreadable`
3. `page_flag == "low_confidence"` → `low_confidence`
4. vlm text empty → `unreadable`
5. `"ocr" in sources` → dual branch: ocr.conf ≥0.7 and sim ≥0.85 → `ok`; ocr.conf ≥0.7 and sim <0.85 → `ocr_preferred`; ocr.conf <0.7 and vlm text non-empty → `vlm_lowconf`; ocr.conf <0.7 and vlm empty → already handled by 4
6. else → `ok`

- [ ] **Step 1: Failing tests**:

```python
def _r(text="Hello world", conf=None, is_image=False, ocr=None):
    src = {"vlm": SourceResult(text=text, confidence=None)}
    if ocr: src["ocr"] = SourceResult(*ocr)
    return Region(id="p1r0", bbox=(1, 2, 3, 4), sources=src, is_image=is_image)

def test_ok_vlm_only():
    assert resolve(_r(), "ok") == "ok"

def test_image_region_wins_over_unreadable_page():
    assert resolve(_r(text="", is_image=True), "unreadable") == "image_unextractable"

def test_unreadable_page_empty_text():
    assert resolve(_r(text=""), "unreadable") == "unreadable"

def test_low_confidence_page():
    assert resolve(_r(), "low_confidence") == "low_confidence"

def test_empty_vlm_on_ok_page_is_unreadable():
    assert resolve(_r(text=""), "ok") == "unreadable"

def test_dual_agree():
    assert resolve(_r(text="The cat sat.", ocr=("The cat sat.", 0.95)), "ok") == "ok"

def test_dual_ocr_preferred():
    assert resolve(_r(text="The car set.", ocr=("The cat sat.", 0.95)), "ok") == "ocr_preferred"

def test_dual_vlm_lowconf():
    assert resolve(_r(text="The cat sat.", ocr=("", 0.3)), "ok") == "vlm_lowconf"

def test_normalize_and_similarity():
    assert normalize("A. The Cat, sat!") == "a the cat sat"
    assert similarity("The cat sat", "the cat  sat") > 0.95
    assert similarity("", "") == 0.0

def test_zero_conf_means_untrustworthy():
    assert resolve(_r(text="x", ocr=("completely different text here", 0.0)), "ok") == "vlm_lowconf"
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces + resolution order. `normalize`: lowercase, strip punctuation (regex `[^\w\s]`), collapse whitespace, map `0→o`, `1→l`, `5→s` inside words only (simple str.translate on whole string is acceptable MVP).
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(worker): verdict resolution with dual-source branch`

---

### Task 3: Adapter + page/result builders

**Files:**
- Create: `worker/pipeline.py`, `worker/tests/fixtures/res_json_canned.json`, `worker/tests/test_pipeline_build.py`

**Interfaces:**
- Consumes: `verdict.precheck`, `verdict.resolve`, `verdict.SourceResult/Region`.
- Produces: `res_json_to_regions(res_json: dict) -> list[Region]` (layout list → Regions, `is_image = type=="image"`, rec_texts joined for text regions, rec_scores mean → confidence); `page_markdown_from(res_json: dict, regions: list[Region], page_flag: str, page_index: int) -> str` (trusts VLM markdown order; replaces placeholder tokens `[image]`/`![...]` for image regions with warning marker; appends marker list under `## Cảnh báo` for image regions without placeholder token); `build_page(res_json, page_index, precheck_img, inference_ran: bool) -> dict` (spec §4 page shape); `build_result(pages: list[dict], gpu_seconds: float, model_version: str = "PaddleOCR-VL-1.5-0.9B") -> dict` (spec §4 top shape incl. `warnings` list from page_flags).

- [ ] **Step 1: Failing tests** `worker/tests/test_pipeline_build.py` (canned fixture: title region "Midterm Test", text region "Part 2\n5. A. cat B. car C. cap D. can", image region placeholder `[image]`, table region with pipes):

```python
def test_adapter_maps_regions():
    regions = res_json_to_regions(load_fixture("res_json_canned.json"))
    assert [r.id for r in regions] == ["p1r0", "p1r1", "p1r2", "p1r3"]
    assert regions[2].is_image and regions[2].bbox is not None

def test_page_markdown_structure_fidelity():
    fx = load_fixture("res_json_canned.json")
    regions = res_json_to_regions(fx)
    md = page_markdown_from(fx, regions, "ok", 1)
    assert "## Midterm Test" in md                       # title → ##
    assert "5. A. cat B. car C. cap D. can" in md        # numbering verbatim
    assert "| Q1 |" in md                                # table pipes preserved
    assert "**[Hình ảnh chưa trích xuất: vùng p1r2]**" in md  # marker replaces [image]

def test_build_result_shape_matches_spec():
    fx = load_fixture("res_json_canned.json")
    regions = res_json_to_regions(fx)
    page = build_page(fx, 1, inference_ran=True)
    result = build_result([page], gpu_seconds=12.5)
    assert set(result) >= {"model_version", "gpu_seconds", "warnings", "markdown", "pages"}
    assert result["model_version"] == "PaddleOCR-VL-1.5-0.9B"
    assert result["gpu_seconds"] == 12.5
    assert page["regions"][0]["verdict"] in {"ok", "image_unextractable", "unreadable", "low_confidence"}
    assert page["regions"][0]["bbox"] == [1, 2, 3, 4]

def test_unreadable_page_skips_inference():
    fx = load_fixture("res_json_canned.json")
    page = build_page(fx, 3, inference_ran=False)   # precheck both-fail path
    assert page["page_flag"] == "unreadable"
    assert page["regions"] == []
    assert "Không trích xuất được văn bản" in page["markdown"]
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces. `build_page` decides page_flag from an injected `PrecheckResult` (signature: `build_page(res_json, page_index, precheck: PrecheckResult | None, inference_ran: bool)`; `None` precheck = test shortcut for "ok").
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(worker): res.json adapter and result builders`

---

### Task 4: `run_job` loop

**Files:**
- Create: `worker/tests/test_run_job.py`
- Modify: `worker/pipeline.py`

**Interfaces:**
- Produces: `RunnerAuthError(Exception)`; `run_job(base_url: str, runner_key: str, client: httpx.Client, pipeline_factory: Callable[[], Any], sleep_fn: Callable[[float], None], rasterize_fn: Callable[[bytes, str], list[tuple[bytes, int, int]]] = default_pdftoppm) -> int` (returns jobs processed; loops forever unless `RunnerAuthError` raised — tests inject a `max_jobs` guard via `sleep_fn` raising StopIteration after N). Page images passed as `(png_bytes, width, height)`; `pipeline_factory().predict` duck-typed: test fake returns object with `.json` dict.

- [ ] **Step 1: Failing tests** (httpx.MockTransport; fake pipeline returning canned fixture; records all requests):

```python
def test_full_job_success_calls_heartbeat_per_page_and_result(mock_transport_state, tmp_path):
    # next → job(2 pages) ; result200
    n = run_job(BASE, "key", httpx.Client(transport=mock_transport_state.transport),
                pipeline_factory=lambda: FakePipeline(), sleep_fn=noop_guard(1))
    assert n == 1
    paths = [r.url.path for r in mock_transport_state.requests]
    assert paths.count("/api/jobs/1/heartbeat") == 2          # per page
    assert paths[-1] == "/api/jobs/1/result"
    result = mock_transport_state.last_json("/api/jobs/1/result")
    assert result["gpu_seconds"] >= 0 and len(result["pages"]) == 2

def test_401_stops_without_fail():
    # /next returns 401
    with pytest.raises(RunnerAuthError):
        run_job(BASE, "bad", client, pipeline_factory=FakePipeline, sleep_fn=noop_guard(1))
    assert not any(r.url.path.endswith("/fail") for r in state.requests)

def test_processing_exception_posts_fail_then_continues():
    # first job: pipeline.predict raises; second job succeeds
    n = run_job(BASE, "key", client, pipeline_factory=flaky_factory, sleep_fn=noop_guard(2))
    assert n == 1
    fails = [r for r in state.requests if r.url.path.endswith("/fail")]
    assert len(fails) == 1 and len(fails[0].json()["error"]) <= 500

def test_pdf_routed_through_rasterize():
    # file_type=pdf → rasterize_fn called with bytes; images bypassed
    run_job(BASE, "key", client, pipeline_factory=FakePipeline, sleep_fn=noop_guard(1),
            rasterize_fn=fake_raster)
    assert state.rasterize_called is True
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces: download via `client.get(file_url)`; pdf → `rasterize_fn`; per page: precheck → maybe `predict` → `build_page` → heartbeat; `result` via shared `build_result`; error paths per Global Constraints. `default_pdftoppm`: `pdftoppm -r 200 -png` into tempdir (poppler assumed installed; Plan G docs).
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(worker): job loop with heartbeat, fail handling, auth stop`

---

### Task 5: Colab notebook + smoke checklist

**Files:**
- Create: `worker/colab_notebook.ipynb`, `docs/colab-smoke-checklist.md`

**Interfaces:**
- Consumes: `worker/pipeline.run_job`, `verdict.precheck`; notebook imports pipeline via `%run` or `sys.path.insert` (ponytail: no packaging on Colab).

- [ ] **Step 1: Write notebook cells** (no automated test — Colab-only):
  1. Setup: `!apt-get -qq install -y poppler-utils`, `!pip install -q paddlepaddle-gpu paddleocr httpx opencv-python-headless rapidfuzz pypdf pillow`
  2. Secrets: `from google.colab import userdata; BASE_URL = userdata.get("BASE_URL"); RUNNER_KEY = userdata.get("RUNNER_KEY")` (retry loop on `userdata.SecretNotFoundError`)
  3. Smoke cell (run ONCE manually before loop): `pipeline.predict("TA.jpg")` → `print(res.json.keys())` → compare against adapter assumption; record actual keys in checklist doc
  4. Init: `from paddleocr import PaddleOCRVL; PIPELINE = PaddleOCRVL(pipeline_version="v1.5", vl_rec_model_name="PaddleOCR-VL-1.5-0.9B", layout_detection_model_name="PP-DocLayoutV3")`
  5. Loop: `sys.path.insert(0, "worker"); from pipeline import run_job; run_job(BASE_URL, RUNNER_KEY, httpx.Client(timeout=60), pipeline_factory=lambda: PIPELINE, sleep_fn=time.sleep)`
- [ ] **Step 2: Manual smoke on real Colab** (human gate — do not skip): run smoke cell on `TA.jpg`, fill `docs/colab-smoke-checklist.md` with real `res.json` keys; if shape ≠ assumption → adjust `res_json_to_regions` (one function) and re-run `cd worker && pytest -v` before committing.
- [ ] **Step 3: Commit** `feat(worker): colab notebook + smoke checklist`

---

**Plan C done when:** `cd worker && pytest -v` green; notebook committed; checklist filled after real-Colab smoke.
