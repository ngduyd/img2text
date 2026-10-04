import cv2
import numpy as np
from PIL import Image, ImageDraw

from verdict import precheck


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
