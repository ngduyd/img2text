# Colab smoke checklist — img2text worker (Plan C)

Human gate. Run against real Colab (GPU) after uploading the repo. Tick each box and fill the blanks.
Notebook: `worker/colab_notebook.ipynb`.

## 1. Secrets

- [ ] `BASE_URL` and `RUNNER_KEY` set in Colab Secrets (🔑) (notebook cell retries until set)

## 2. Setup cell

- [ ] apt poppler-utils install ran clean
- [ ] pip install ran clean (`paddlepaddle-gpu paddleocr httpx opencv-python-headless rapidfuzz pypdf pillow numpy`)
- [ ] poppler present: `pdftoppm -v` printed version

## 3. Smoke cell (run ONCE manually, before the loop)

Upload a test image as `TA.jpg` into `/content/`, run the smoke cell.

- [ ] smoke cell ran clean

**ACTUAL `res.json` keys printed:**

```
(record here — copy the printed list verbatim)
```

**Compare vs adapter assumption** in `worker/pipeline.py` (`res_json_to_regions` expects
`layout` list with `type`/`bbox`/`rec_texts`/`rec_scores` + top-level `markdown`):

- [ ] `layout` key present — [ ] matches assumption — mismatches:
- [ ] `markdown` key present — [ ] matches assumption — mismatches:

**Mismatches / notes:**

```
(none, or describe — a shape mismatch changes res_json_to_regions in worker/pipeline.py)
```

Artifacts: `/tmp/smoke_out/*.txt` (one per key) and `/tmp/smoke_out/page.md`.

## 4. Loop cell (real queued job)

- [ ] loop cell ran against a real queued job from the server
- [ ] job completed and result accepted by server
- [ ] `RunnerAuthError` NOT raised (bearer key accepted)

If not done: **no server yet — loop verified later in e2e** (leave unchecked, write that here).

```
(date / outcome)
```
