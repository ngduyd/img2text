import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
from PIL import Image

from pipeline import RunnerAuthError, run_job

BASE = "http://worker.test"
CANNED = json.loads((Path(__file__).parent / "fixtures" / "res_json_canned.json").read_text())


def _png(w, h, sharp=True):
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 256, (h, w), dtype=np.uint8) if sharp else np.full((h, w), 255, np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "L").save(buf, "PNG")
    return buf.getvalue()


def _pdf_two_pages():
    rng = np.random.default_rng(1)
    a = Image.fromarray(rng.integers(0, 256, (300, 400), dtype=np.uint8), "L")
    b = Image.fromarray(rng.integers(2, 250, (300, 400), dtype=np.uint8), "L")
    buf = io.BytesIO()
    a.save(buf, "PDF", save_all=True, append_images=[b])
    return buf.getvalue()


def _job(job_id=1, file_type="image", page_count=1, file_url="http://files.test/f.bin"):
    return {"job_id": job_id, "worker_token": "tok1", "file_url": file_url,
            "file_type": file_type, "page_count": page_count}


class State:
    """httpx.MockTransport recorder: all requests logged; /next served in order,
    raises StopIteration guard (before logging) when exhausted."""

    def __init__(self, next_responses, file_bytes=b""):
        self.requests = []
        self.next_responses = list(next_responses)
        self.file_bytes = file_bytes
        self.rasterize_called = False

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
            return httpx.Response(200, json={"lease_expires_at": "2026-10-04T00:00:00Z"})
        if path.endswith("/result"):
            return httpx.Response(200, json={})
        if path.endswith("/fail"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    def last_json(self, path):
        for r in reversed(self.requests):
            if r.url.path == path:
                return json.loads(r.content)
        raise AssertionError(f"no request logged for {path}")


def noop_guard(n):
    """Brief binding: sleep_fn raises StopIteration-style guard after N calls;
    also asserts run_job passes a 5-30s delay."""
    calls = {"n": 0}

    def _sleep(delay):
        assert 5 <= delay <= 30
        calls["n"] += 1
        if calls["n"] > n:
            raise StopIteration("guard")

    return _sleep


class FakePipeline:
    def predict(self, img):
        return SimpleNamespace(json=CANNED)

class FakePipelineNoDims:
    """res.json without width/height → run_job setdefault must fill raster dims."""
    def predict(self, img):
        return SimpleNamespace(json={k: v for k, v in CANNED.items()
                                    if k not in ("width", "height")})

class FlakyPipeline:
    def predict(self, img):
        raise RuntimeError("boom " * 200)


def flaky_factory():
    calls = {"n": 0}

    def _f():
        calls["n"] += 1
        return FlakyPipeline() if calls["n"] == 1 else FakePipeline()

    return _f


def test_full_job_success_calls_heartbeat_per_page_and_result():
    state = State(
        [httpx.Response(200, json=_job(file_type="pdf", page_count=2))],
        file_bytes=_pdf_two_pages(),
    )
    client = httpx.Client(transport=state.transport)
    n = run_job(BASE, "key", client, pipeline_factory=lambda: FakePipeline(), sleep_fn=noop_guard(1))
    assert n == 1
    paths = [r.url.path for r in state.requests]
    assert paths.count("/api/jobs/1/heartbeat") == 2          # per page
    assert paths[-1] == "/api/jobs/1/result"
    result = state.last_json("/api/jobs/1/result")
    assert result["gpu_seconds"] >= 0 and len(result["pages"]) == 2
    assert all(p["width"] > 0 and p["height"] > 0 for p in result["pages"])

def test_inference_pages_get_dims_from_raster_when_res_json_lacks_them():
    state = State([httpx.Response(200, json=_job(file_type="pdf", page_count=1))],
                  file_bytes=b"%PDF-1.4 fake")
    client = httpx.Client(transport=state.transport)

    def fake_raster(data, file_type):
        return [(_png(1200, 800), 1200, 800)]

    run_job(BASE, "key", client, pipeline_factory=lambda: FakePipelineNoDims(),
            sleep_fn=noop_guard(1), rasterize_fn=fake_raster)
    pages = state.last_json("/api/jobs/1/result")["pages"]
    assert [(p["width"], p["height"]) for p in pages] == [(1200, 800)]

def test_next_500_backoff_continues_without_parsing_body():
    state = State([httpx.Response(500, text="<html>boom</html>"),
                   httpx.Response(200, json=_job())],
                  file_bytes=_png(1200, 800))
    client = httpx.Client(transport=state.transport)
    n = run_job(BASE, "key", client, pipeline_factory=lambda: FakePipeline(), sleep_fn=noop_guard(2))
    assert n == 1

def test_401_stops_without_fail():
    state = State([httpx.Response(401)])
    client = httpx.Client(transport=state.transport)
    try:
        run_job(BASE, "bad", client, pipeline_factory=FakePipeline, sleep_fn=noop_guard(1))
        raise AssertionError("expected RunnerAuthError")
    except RunnerAuthError:
        pass
    assert not any(r.url.path.endswith("/fail") for r in state.requests)


def test_processing_exception_posts_fail_then_continues():
    state = State(
        [httpx.Response(200, json=_job()), httpx.Response(200, json=_job())],
        file_bytes=_png(1200, 800),
    )
    client = httpx.Client(transport=state.transport)
    n = run_job(BASE, "key", client, pipeline_factory=flaky_factory(), sleep_fn=noop_guard(2))
    assert n == 1
    fails = [r for r in state.requests if r.url.path.endswith("/fail")]
    assert len(fails) == 1 and len(json.loads(fails[0].content)["error"]) <= 500


def test_pdf_routed_through_rasterize():
    state = State([httpx.Response(200, json=_job(file_type="pdf", page_count=1))],
                  file_bytes=b"%PDF-1.4 fake")
    client = httpx.Client(transport=state.transport)

    def fake_raster(data, file_type):
        state.rasterize_called = True
        return [(_png(1200, 800), 1200, 800)]

    run_job(BASE, "key", client, pipeline_factory=FakePipeline, sleep_fn=noop_guard(1),
            rasterize_fn=fake_raster)
    assert state.rasterize_called is True
