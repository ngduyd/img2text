"""Image quality precheck: blur detection via Laplacian variance, width gate."""

from dataclasses import dataclass

import cv2
import numpy as np

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
