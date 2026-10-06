"""Image quality precheck (Laplacian variance, width gate) + verdict resolution.

Verdict MVP emits only ok|image_unextractable|unreadable|low_confidence
(sources={"vlm"} only). ocr_preferred/vlm_lowconf are reserved for future
OCR binding; the dual-source branch is implemented + tested now.
"""

import re
from dataclasses import dataclass

import cv2
import numpy as np
from rapidfuzz import fuzz

BLUR_LAPLACIAN_THRESHOLD = 100
MIN_WIDTH_PX = 1000


@dataclass
class PrecheckResult:
    blurry: bool
    too_small: bool


def precheck(img: np.ndarray) -> PrecheckResult:
    if img is None or img.size == 0:
        raise ValueError("empty image array")
    if img.ndim == 2:
        gray = img
    elif img.ndim == 3 and img.shape[2] == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError(f"unsupported image shape: {img.shape}")
    # ponytail: glyph-height check (<20px estimated) is upgrade path, not implemented.
    blurry = float(cv2.Laplacian(gray, cv2.CV_64F).var()) < BLUR_LAPLACIAN_THRESHOLD
    too_small = img.shape[1] < MIN_WIDTH_PX
    return PrecheckResult(blurry=blurry, too_small=too_small)


@dataclass
class SourceResult:
    text: str
    confidence: float | None


@dataclass
class Region:
    id: str
    bbox: tuple[int, int, int, int] | None
    sources: dict[str, SourceResult]
    is_image: bool = False


_OCR_CONF_THRESHOLD = 0.7
_SIM_THRESHOLD = 0.85

_DIGIT_MAP = str.maketrans({"0": "o", "1": "l", "5": "s"})


def normalize(text: str) -> str:
    """lowercase, strip punctuation, collapse whitespace, map 0→o 1→l 5→s."""
    t = re.sub(r"[^\w\s]", "", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t.translate(_DIGIT_MAP)


def similarity(a: str, b: str) -> float:
    """0–1 fuzzy similarity on normalized text; empty-vs-empty is 0.0."""
    if not a and not b:
        return 0.0
    return fuzz.ratio(normalize(a), normalize(b)) / 100.0


def resolve(region: Region, page_flag: str) -> str:
    """Pinned resolution order: image > page_flag > empty vlm > dual branch > ok."""
    if region.is_image:
        return "image_unextractable"
    if page_flag == "unreadable":
        return "unreadable"
    if page_flag == "low_confidence":
        return "low_confidence"
    vlm = region.sources.get("vlm")
    if vlm is None or not vlm.text.strip():
        return "unreadable"
    ocr = region.sources.get("ocr")
    if ocr is not None:
        conf = ocr.confidence if ocr.confidence is not None else 0.0
        sim = similarity(vlm.text, ocr.text)
        if conf < _OCR_CONF_THRESHOLD:
            return "vlm_lowconf"
        return "ok" if sim >= _SIM_THRESHOLD else "ocr_preferred"
    return "ok"
