"""Task 2 brief: preprocess page filter + clockwise rotation (plan W).

Fake rasterize returns 4 numbered pages: solid color + white marker quadrant
at top-left. Rotation probe: clockwise 90 moves marker top-left → top-right
and swaps dims. R55 binding: filtered result pages keep ORIGINAL 1-based page
numbers as index (pages [2,4] → indices [2,4], not 1..k).
"""

import io
import json
from types import SimpleNamespace

import httpx
import numpy as np
from PIL import Image

from pipeline import run_job

BASE = "http://worker.test"
COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]  # pages 1..4
W, H = 1200, 900   # ≥ MIN_WIDTH_PX=1000, non-blurry (verdict.precheck gate)
MARKER = 100       # white square at top-left corner of each page
TOL = 40           # noise tolerance for color probes


def _near(px, color, tol=TOL):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, color))


def _page_png(n):
    rng = np.random.default_rng(0)  # deterministic → rotate-0 byte-equivalence
    noise = rng.integers(-20, 21, (H, W, 3), dtype=np.int16)
    arr = np.clip(np.array(COLORS[n - 1], dtype=np.int16) + noise, 0, 255).astype(np.uint8)
    arr[:MARKER, :MARKER] = 255  # rotation-detectable marker, top-left
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def _fake_raster(data, file_type):
    return [(_page_png(n), W, H) for n in range(1, 5)]


def _job(preprocess, job_id=1):
    j = {"job_id": job_id, "worker_token": "tok1", "file_url": "http://files.test/f.bin",
         "file_type": "pdf", "page_count": 4}
    if preprocess is not None:
        j["preprocess"] = preprocess
    return j


class State:
    def __init__(self, next_responses, file_bytes=b""):
        self.requests = []
        self.next_responses = list(next_responses)
        self.file_bytes = file_bytes

    @property
    def transport(self):
        return httpx.MockTransport(self._handle)

    def _handle(self, request):
        path = request.url.path
        if path == "/api/jobs/next":
            if not self.next_responses:
                raise StopIteration("next exhausted")
            self.requests.append(request)
            return self.next_responses.pop(0)
        self.requests.append(request)
        if path == "/f.bin":
            return httpx.Response(200, content=self.file_bytes)
        if path.endswith("/heartbeat"):
            return httpx.Response(200, json={})
        if path.endswith("/result"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    def last_json(self, path):
        for r in reversed(self.requests):
            if r.url.path == path:
                return json.loads(r.content)
        raise AssertionError(f"no request logged for {path}")

    def count(self, suffix):
        return sum(1 for r in self.requests if r.url.path.endswith(suffix))


class CapturingPipeline:
    """Records arrays passed to predict; serves minimal res.json (dims from raster)."""
    arrs = []

    def predict(self, img):
        CapturingPipeline.arrs.append(np.array(img))
        return SimpleNamespace(json={"layout": [], "markdown": ""})


def _run(preprocess):
    CapturingPipeline.arrs = []
    state = State([httpx.Response(200, json=_job(preprocess))], file_bytes=b"%PDF fake")
    client = httpx.Client(transport=state.transport)

    def guard(delay):
        raise StopIteration("guard")

    run_job(BASE, "key", client, pipeline_factory=lambda: CapturingPipeline(),
            sleep_fn=guard, rasterize_fn=_fake_raster)
    return state, state.last_json("/api/jobs/1/result")


def test_filter_pages_keeps_original_1based_indices():
    """R55: pages [2,4] → result indices [2,4], exactly 2 pages processed."""
    state, result = _run({"pages": [2, 4]})
    assert [p["index"] for p in result["pages"]] == [2, 4]  # NOT [1, 2]
    assert len(result["pages"]) == 2
    assert len(CapturingPipeline.arrs) == 2                 # only 2 predictions
    assert state.count("/heartbeat") == 2                   # heartbeat per processed page
    for arr, n in zip(CapturingPipeline.arrs, [2, 4]):
        assert _near(arr[50, W // 2], COLORS[n - 1])  # right pages kept (interior, past marker)


def test_rotate_90_swaps_dims_and_rotates_clockwise():
    """rotate {"2":90}: page 2 dims swapped; marker top-left → top-right (CW)."""
    state, result = _run({"rotate": {"2": 90}})
    assert [p["index"] for p in result["pages"]] == [1, 2, 3, 4]
    p2 = result["pages"][1]
    assert (p2["width"], p2["height"]) == (H, W)  # swapped
    arr = CapturingPipeline.arrs[1]
    assert arr.shape[:2] == (W, H)                # 900 wide × 1200 tall
    assert _near(arr[50, H - 50], (255, 255, 255))  # marker now top-right (CW 90)
    assert _near(arr[50, 50], COLORS[1])            # top-left = orig bottom-left (page color)
    assert _near(arr[W - 50, 50], COLORS[1])        # bottom-left = orig bottom-right (page color)


def test_absent_preprocess_keeps_all_four_pages():
    """Regression: no preprocess key → today's behavior, indices 1..4."""
    for preprocess in (None, {}):
        state, result = _run(preprocess)
        assert [p["index"] for p in result["pages"]] == [1, 2, 3, 4]
        assert all((p["width"], p["height"]) == (W, H) for p in result["pages"])


def test_rotate_zero_is_noop():
    """rotate 0 = no-op: dims unchanged, content byte-equivalent."""
    state, result = _run({"rotate": {"2": 0}})
    p2 = result["pages"][1]
    assert (p2["width"], p2["height"]) == (W, H)
    orig = np.array(Image.open(io.BytesIO(_page_png(2))))
    assert np.array_equal(CapturingPipeline.arrs[1], orig)
