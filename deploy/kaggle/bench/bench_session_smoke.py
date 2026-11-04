"""Smoke test trên Kaggle cho CODE SẢN XUẤT mới (không phải bench demo).

Chạy đúng các hàm vừa sửa trong `deploy/kaggle/kernel/`:
  1. `kb.install_parent_deps()` (uv có sẵn → bỏ pip uv)
  2. SONG SONG: `kb._bootstrap_venv_packages` (paddle) ∥ `sess.prewarm_rembg` (u2net)
  3. `kb.page_rgba` (rembg cả trang) → `kb.extract_crops(rgba_pages=...)` cắt RGBA theo bbox
  4. `sess.get_rembg_session()` chỉ tạo session 1 lần

Mục tiêu: chứng minh wiring chạy được và đo lại số trên code thật, không phải để lấy số đẹp.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "/kaggle/working/bench_session_smoke_result.json"
IMAGE_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/"
    "paddleocr_vl_demo.png"
)


def log(msg: str) -> None:
    print(f"[smoke] {msg}", flush=True)


def main() -> int:
    R: dict = {"gpu": subprocess.run(
        ["nvidia-smi", "--query-gpu-name", "--format=csv,noheader"],
        capture_output=True, text=True, check=False).stdout.strip()}
    t_all = time.perf_counter()

    import img2text_batch as kb
    import img2text_session as sess

    # 1. parent deps (uv có sẵn → không pip install uv)
    labels: list[str] = []
    t = time.perf_counter()
    kb.install_parent_deps(labels.append)
    R["parent_deps_s"] = round(time.perf_counter() - t, 2)
    R["parent_labels"] = labels
    kb.bind_runtime_modules()

    # 2. song song: paddle packages ∥ prewarm u2net
    boot_labels: list[str] = []
    errs: list = []
    t = time.perf_counter()

    def _boot():
        try:
            kb._bootstrap_venv_packages(boot_labels.append)
        except BaseException as exc:  # noqa: BLE001
            errs.append(exc)

    def _warm():
        try:
            sess.prewarm_rembg()
        except BaseException as exc:  # noqa: BLE001
            errs.append(exc)

    tb = threading.Thread(target=_boot, daemon=False)
    tw = threading.Thread(target=_warm, daemon=False)
    tb.start()
    tw.start()
    tb.join()
    tw.join()
    R["parallel_s"] = round(time.perf_counter() - t, 2)
    R["boot_labels"] = boot_labels
    R["errors"] = [f"{type(e).__name__}: {e}" for e in errs]
    if errs:
        log(f"lỗi trong thread: {R['errors']}")

    # 3. page_rgba + extract_crops(rgba_pages=...)
    R["session_cached"] = sess.get_rembg_session() is sess.get_rembg_session()
    urllib.request.urlretrieve(IMAGE_URL, "/tmp/smoke.png")
    import fitz
    doc = fitz.open()
    rect = fitz.open("/tmp/smoke.png")[0].rect
    doc.new_page(width=rect.width, height=rect.height).insert_image(
        fitz.Rect(0, 0, rect.width, rect.height), filename="/tmp/smoke.png"
    )
    doc.save("/tmp/smoke.pdf")
    doc.close()

    t = time.perf_counter()
    rgba = kb.page_rgba("/tmp/smoke.pdf", 1, session=sess.get_rembg_session())
    R["page_rgba_s"] = round(time.perf_counter() - t, 2)
    R["rgba_bytes"] = len(rgba or b"")
    if not rgba:
        R["FAIL"] = "page_rgba None"
        json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=2)
        log(json.dumps(R, ensure_ascii=False))
        return 1

    from PIL import Image
    import io
    rgba_im = Image.open(io.BytesIO(rgba))
    R["rgba_size"] = list(rgba_im.size)
    R["rgba_mode"] = rgba_im.mode

    W, H = rgba_im.size
    pages_out = [{
        "page": 1, "width": W, "height": H,
        "blocks": [{"id": "b_smoke", "type": "image",
                    "bbox": [W * 0.2, H * 0.2, W * 0.8, H * 0.8], "text": ""}],
    }]
    t = time.perf_counter()
    crops = kb.extract_crops("/tmp/smoke.pdf", pages_out, rgba_pages={1: rgba})
    R["extract_crops_s"] = round(time.perf_counter() - t, 3)
    R["crops"] = {k: len(v) for k, v in crops.items()}
    if crops:
        cut = Image.open(io.BytesIO(next(iter(crops.values()))))
        R["crop_size"] = list(cut.size)
        R["crop_mode"] = cut.mode
        alpha = cut.getchannel("A")
        R["crop_alpha_min"] = alpha.getextrema()[0]
        R["crop_alpha_max"] = alpha.getextrema()[1]

    R["total_s"] = round(time.perf_counter() - t_all, 2)
    ok = bool(crops) and R["rgba_bytes"] > 0 and R["crop_mode"] == "RGBA"
    R["PASS"] = ok
    log(json.dumps(R, ensure_ascii=False))
    json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
