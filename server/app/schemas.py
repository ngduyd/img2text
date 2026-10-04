"""Worker result validation models (Task 4, spec §4 result shape)."""

from typing import Literal

from pydantic import BaseModel

class RegionOut(BaseModel):
    id: str
    bbox: list[int] | None
    text: str
    verdict: Literal["ok", "image_unextractable", "unreadable", "low_confidence"]
    placeholder: bool

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
