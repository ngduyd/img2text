"""Guard tất định trên OCR result — biến lỗi âm thầm thành warning.

Không sửa gì, không gọi LLM. Chạy ở ingest (`job_results._store`), nối vào
`result["warnings"]` dạng `p{page}:{kind}:{detail}` để UI/operator thấy ngay
trang nào cần so ảnh crop (`/regions/{rid}/crop`) hoặc re-OCR.

Bắt được: hallucination/loop decode (density, dup_text), mất nội dung
(empty_region, low_coverage), toạ độ sai/lệch DPI (bbox_out, bbox_overlap),
tín hiệu OCR tự tin thấp (low_conf). KHÔNG bắt được text sai mà vẫn "trông
bình thường" ("50%" → "80%") — cái đó cần người đọc.
"""

from __future__ import annotations

import logging
import statistics

logger = logging.getLogger(__name__)

# ngưỡng — chỉnh sau khi có số liệu thật (xem docs/bench, chưa đủ mẫu)
DENSITY_LO = 0.25        # < 0.25× median trang → nghi cắt cụt / đọc watermark
DENSITY_HI = 4.0         # > 4× median → nghi loop decode
DENSITY_MIN_CHARS = 5    # region quá ngắn thì density vô nghĩa
EMPTY_AREA_RATIO = 0.01  # region rỗng mà chiếm ≥1% diện tích trang
DUP_MIN_CHARS = 8
DUP_MIN_COUNT = 3        # cùng chuỗi ≥3 lần TRONG 1 trang
OVERLAP_RATIO = 0.8      # IoU > 0.8 → 2 region cùng vùng
BBOX_TOL = 0.02          # cho phép tràn 2% (làm tròn px)
MIN_COVERAGE = 0.05      # tổng diện tích region < 5% trang
MAX_REPORT_PER_KIND = 3  # 1 trang 50 region lỗi → 3 dòng đủ, tránh spam


def _bbox(region: dict) -> list[float] | None:
    b = region.get("bbox")
    if not b or len(b) != 4:
        return None
    return [float(v) for v in b]


def _area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _density(text: str, b: list[float]) -> float:
    area = _area(b)
    return len(text) / area if area > 0 else 0.0


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def check_result(result: dict) -> list[str]:
    """Trả list warning `p{page}:{kind}:{detail}` (page = index 0-based)."""
    out: list[str] = []
    for pi, page in enumerate(result.get("pages") or []):
        regions = [r for r in page.get("regions") or [] if _bbox(r)]
        pw = float(page.get("width") or 0)
        ph = float(page.get("height") or 0)
        page_area = pw * ph
        if not regions or page_area <= 0:
            continue

        boxes = [_bbox(r) for r in regions]
        texts = [str(r.get("text") or "") for r in regions]

        # 1. density bất thường so với median CỦA CHÍNH TRANG (bảng/nhiều
        # khoảng trắng khác trang chữ đặc → ngưỡng tuyệt đối sẽ sai)
        dens = [
            _density(t, b) for t, b in zip(texts, boxes)
            if len(t.strip()) >= DENSITY_MIN_CHARS
        ]
        if len(dens) >= 3:
            med = statistics.median(dens)
            if med > 0:
                hits = sum(1 for d in dens if d < med * DENSITY_LO or d > med * DENSITY_HI)
                if hits:
                    out.append(f"p{pi}:density:{hits}/{len(dens)} region lệch >4×/0.25× median")

        # 2. region rỗng mà chiếm diện tích lớn
        empty = sum(
            1 for t, b in zip(texts, boxes)
            if not t.strip() and _area(b) >= page_area * EMPTY_AREA_RATIO
        )
        if empty:
            out.append(f"p{pi}:empty_region:{empty} region rỗng chiếm ≥1% trang")

        # 3. text trùng lặp trong cùng trang (loop decode); header/footer lặp
        # GIỮA các trang là hợp lệ nên chỉ xét trong trang
        seen: dict[str, int] = {}
        for t in texts:
            key = t.strip()
            if len(key) >= DUP_MIN_CHARS:
                seen[key] = seen.get(key, 0) + 1
        dups = sum(1 for c in seen.values() if c >= DUP_MIN_COUNT)
        if dups:
            out.append(f"p{pi}:dup_text:{dups} chuỗi lặp ≥{DUP_MIN_COUNT} lần trong trang")

        # 4. bbox ngoài trang / chồng lấn
        tol_x, tol_y = pw * BBOX_TOL, ph * BBOX_TOL
        outside = sum(
            1 for b in boxes
            if b[0] < -tol_x or b[1] < -tol_y or b[2] > pw + tol_x or b[3] > ph + tol_y
        )
        if outside:
            out.append(f"p{pi}:bbox_out:{outside} region ngoài biên trang (nghi lệch DPI)")

        # ponytail: O(n²) — trang >120 region thì bỏ qua check overlap
        # (chi phí không đáng; nâng bằng sort theo x nếu thực tế cần)
        if len(boxes) <= 120:
            overlaps = 0
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    if _iou(boxes[i], boxes[j]) > OVERLAP_RATIO:
                        overlaps += 1
                        if overlaps >= MAX_REPORT_PER_KIND:
                            break
            if overlaps:
                out.append(f"p{pi}:bbox_overlap:{overlaps}+ region trùng vùng (IoU>0.8)")

        # 5. độ phủ trang thấp — nghi OCR bỏ gần hết trang
        cover = sum(_area(b) for b in boxes) / page_area
        if cover < MIN_COVERAGE:
            out.append(f"p{pi}:low_coverage:{cover:.1%} diện tích trang")

        # 6. tín hiệu tự tin sẵn có của OCR
        low = sum(1 for r in regions if str(r.get("verdict") or "ok") != "ok")
        if low:
            out.append(f"p{pi}:low_conf:{low}/{len(regions)} region verdict≠ok")

    return out
