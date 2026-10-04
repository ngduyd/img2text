"""Adapter (Colab res.json → Region list) + page/result builders (spec §4).

res_json shape assumed: {"layout": [{"type": "text|image|table|title",
"bbox": [x1,y1,x2,y2], "rec_texts": [...], "rec_scores": [...]}],
"markdown": "<page md>"}. Assumption verified against real Colab output in
Task 5 smoke — single-function blast radius if shape drifts.

Contract choice: page_markdown_from PRESERVES VLM markdown structure and only
injects warning markers. Title → "## {text}" mapping (when VLM markdown lacks
headings) happens at notebook/adapter level later, not here.
"""

import glob
import io
import os
import random
import re
import subprocess
import tempfile
import time

import httpx
import numpy as np
from PIL import Image

from verdict import PrecheckResult, Region, SourceResult, precheck, resolve

_UNREADABLE_MARKDOWN = "Không trích xuất được văn bản"
_MARKER = "**[Hình ảnh chưa trích xuất: vùng {region_id}]**"
_PLACEHOLDER_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|\[image\]")

class RunnerAuthError(Exception):
    """Bearer runner_key rejected by GET /api/jobs/next — STOP, no fail POST."""


def _mean(xs):
    return sum(xs) / len(xs) if xs else None

def res_json_to_regions(res_json: dict, page_index: int = 1) -> list[Region]:
    """layout list → Regions; region id = f"p{page_index}r{i}".

    is_image = type=="image"; rec_texts joined "\\n"; rec_scores mean →
    confidence on the vlm SourceResult.
    """
    regions = []
    for i, item in enumerate(res_json.get("layout", [])):
        texts = item.get("rec_texts") or []
        scores = item.get("rec_scores") or []
        regions.append(Region(
            id=f"p{page_index}r{i}",
            bbox=tuple(item["bbox"]) if item.get("bbox") else None,
            sources={"vlm": SourceResult(text="\n".join(texts), confidence=_mean(scores))},
            is_image=item.get("type") == "image",
        ))
    return regions

def page_markdown_from(res_json: dict, regions: list[Region], page_flag: str, page_index: int) -> str:
    """VLM markdown with image placeholder tokens replaced by warning markers.

    Replaces one placeholder token per image region (`[image]` or
    `![...](...)`); image regions without a placeholder token get markers
    appended under a `## Cảnh báo` heading at the end. Page structure is
    preserved verbatim otherwise.
    """
    md = res_json.get("markdown", "")
    orphans: list[Region] = []
    for region in regions:
        if not region.is_image:
            continue
        marker = _MARKER.format(region_id=region.id)
        if _PLACEHOLDER_RE.search(md):
            md = _PLACEHOLDER_RE.sub(marker, md, count=1)
        else:
            orphans.append(region)
    if orphans:
        md += "\n\n## Cảnh báo\n\n" + "\n\n".join(
            _MARKER.format(region_id=r.id) for r in orphans
        )
    return md

def build_page(res_json: dict, page_index: int, precheck: PrecheckResult | None = None,
               inference_ran: bool = True) -> dict:
    """Spec §4 page shape {index, width, height, page_flag, markdown, regions}.

    precheck None → page_flag "ok" (test shortcut); inference_ran False →
    "unreadable", regions [], unreadable markdown; else flag from precheck
    (both-fail → unreadable, one-fail → low_confidence, none → ok).
    """
    width = res_json.get("width", 0)
    height = res_json.get("height", 0)
    if not inference_ran:
        page_flag = "unreadable"
        regions_out = []
        markdown = _UNREADABLE_MARKDOWN
    else:
        if precheck is None:
            page_flag = "ok"
        elif precheck.blurry and precheck.too_small:
            page_flag = "unreadable"
        elif precheck.blurry or precheck.too_small:
            page_flag = "low_confidence"
        else:
            page_flag = "ok"
        regions = res_json_to_regions(res_json, page_index)
        markdown = page_markdown_from(res_json, regions, page_flag, page_index)
        regions_out = [
            {
                "id": r.id,
                "bbox": list(r.bbox) if r.bbox is not None else None,
                "text": r.sources["vlm"].text,
                "verdict": resolve(r, page_flag),
                "placeholder": r.is_image,
            }
            for r in regions
        ]
    return {
        "index": page_index,
        "width": width,
        "height": height,
        "page_flag": page_flag,
        "markdown": markdown,
        "regions": regions_out,
    }

def build_result(pages: list[dict], gpu_seconds: float,
                 model_version: str = "PaddleOCR-VL-1.5-0.9B") -> dict:
    """Spec §4 top shape. R20: include edited_markdown=None (ResultBody accepts)."""
    return {
        "model_version": model_version,
        "gpu_seconds": gpu_seconds,
        "warnings": [f"page {p['index']}: {p['page_flag']}" for p in pages if p["page_flag"] != "ok"],
        "markdown": "\n\n---\n\n".join(p["markdown"] for p in pages),
        "edited_markdown": None,
        "pages": pages,
    }

def default_pdftoppm(pdf_bytes: bytes, file_type: str) -> list[tuple[bytes, int, int]]:
    """pdftoppm -r 200 -png into tempdir → [(png_bytes, width, height), ...]."""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "input.pdf")
        with open(src, "wb") as f:
            f.write(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "200", "-png", src, os.path.join(td, "page")],
                       check=True, capture_output=True)
        out = []
        names = sorted(glob.glob(os.path.join(td, "page-*.png")),
                       key=lambda p: int(os.path.basename(p).rsplit("-", 1)[1].split(".")[0]))
        for name in names:
            with open(name, "rb") as f:
                data = f.read()
            w, h = Image.open(io.BytesIO(data)).size
            out.append((data, w, h))
        return out

def run_job(base_url: str, runner_key: str, client: httpx.Client, pipeline_factory,
            sleep_fn, rasterize_fn=default_pdftoppm) -> int:
    """Forever job loop → returns jobs processed; raises RunnerAuthError on 401.

    204 → backoff sleep_fn(random.uniform(5, 30)); per page: heartbeat →
    precheck → maybe predict → build_page; result via build_result; 409/422 or
    processing exception → POST /fail {"error": "<class>: <msg≤500>"} → continue.
    ponytail: StopIteration from next/sleep = test loop guard → return count.
    """
    jobs = 0
    runner_hdr = {"Authorization": f"Bearer {runner_key}"}
    while True:
        try:
            r = client.get(f"{base_url}/api/jobs/next", headers=runner_hdr)
        except StopIteration:
            return jobs
        if r.status_code == 401:
            raise RunnerAuthError("runner key rejected by GET /api/jobs/next")
        if r.status_code == 204:
            try:
                sleep_fn(random.uniform(5, 30))
            except StopIteration:
                return jobs
            continue
        job = r.json()
        job_id, token = job["job_id"], job["worker_token"]
        hdr = {"Authorization": f"Bearer {token}"}
        try:
            file_bytes = client.get(job["file_url"]).content
            if job["file_type"] == "pdf":
                raster = rasterize_fn(file_bytes, job["file_type"])
            else:
                im = Image.open(io.BytesIO(file_bytes))
                raster = [(file_bytes, im.size[0], im.size[1])]
            pages: list[dict] = []
            gpu_seconds = 0.0
            for i, (png, w, h) in enumerate(raster, 1):
                client.post(f"{base_url}/api/jobs/{job_id}/heartbeat", headers=hdr)
                arr = np.array(Image.open(io.BytesIO(png)))
                pc = precheck(arr)
                if pc.blurry and pc.too_small:
                    pages.append(build_page({"width": w, "height": h}, i, inference_ran=False))
                else:
                    t0 = time.monotonic()
                    out = pipeline_factory().predict(arr, i)
                    gpu_seconds += time.monotonic() - t0
                    pages.append(build_page(out.json, i, precheck=pc, inference_ran=True))
            rr = client.post(f"{base_url}/api/jobs/{job_id}/result",
                             json=build_result(pages, gpu_seconds), headers=hdr)
            rr.raise_for_status()   # 409/422 → HTTPStatusError → fail below
            jobs += 1
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:500]
            client.post(f"{base_url}/api/jobs/{job_id}/fail", json={"error": err}, headers=hdr)
            continue
