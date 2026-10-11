"""Worker result validation models (Task 4, spec §4 result shape)."""

from typing import Literal

from pydantic import BaseModel, field_validator

# Exact marker cho image region chưa trích xuất — cùng mẫu worker/pipeline.py;
# {region_id} placeholder (khớp 1-1 str.format, giữ nguyên ký tự tiếng Việt).
IMAGE_MARKER = "**[Hình ảnh chưa trích xuất: vùng {region_id}]**"

class PreprocessIn(BaseModel):
    """Plan W upload wizard: page selection + per-page rotation.
    Stored as JSON string in jobs.preprocess (TEXT column)."""

    pages: list[int] | None = None
    rotate: dict[str, int] = {}

class RegionOut(BaseModel):
    id: str
    bbox: list[int] | None
    text: str
    verdict: Literal["ok", "image_unextractable", "unreadable", "low_confidence"]
    placeholder: bool

    @field_validator("bbox")
    @classmethod
    def _bbox_shape(cls, v: list[int] | None) -> list[int] | None:
        # spec §4: bbox is [x1, y1, x2, y2]; Plan D PIL-crops need len==4.
        if v is not None and len(v) != 4:
            raise ValueError("bbox phải có đúng 4 phần tử [x1, y1, x2, y2].")
        return v

class ResultPage(BaseModel):
    index: int
    width: int
    height: int
    page_flag: Literal["ok", "low_confidence", "unreadable"]
    markdown: str
    regions: list[RegionOut]

class ResultBody(BaseModel):
    model_version: str
    gpu_seconds: float
    warnings: list[str]
    markdown: str
    pages: list[ResultPage]
    # spec §4 result JSONB includes edited_markdown (null default); kept so a
    # worker-posted value survives model_dump into job.result (Plan D seam).
    edited_markdown: str | None = None
