"""Kaggle GPU quota (spec kaggle session worker T8, AC6): shared parse/gate.

Tách từ routers/admin._kaggle_quota_payload (response-shape helpers +
HTTP mapping giữ nguyên tên để admin pin test không đổi); orchestrator
dispatch gate dùng quota_remaining_seconds() — không duplicate field-mapping.
"""

import logging
import re

from fastapi import HTTPException

logger = logging.getLogger(__name__)

def _seconds(value) -> float:
    """Kaggle quota duration → float giây. Số pass-through; chuỗi "21600.0s"
    bỏ đuôi "s"; "5900.915.0s" (thừa dấu chấm) → số đầu tiên 5900.915."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        pass
    m = re.match(r"\d+(?:\.\d+)?", text)
    if m is None:
        raise ValueError(f"bad duration: {value!r}")
    return float(m.group())

def _field(obj, name):
    """Response kaggle 2.2.4: attr (proto/dataclass) hoặc dict — cả hai.

    kagglesdk: top-level (ApiGetAcceleratorQuotaStatisticsResponse) alias cả
    camelCase+snake_case; inner ApiAcceleratorQuota chỉ snake_case (timeUsed
    AttributeError → 502). dict JSON thì camelCase.
    """
    if isinstance(obj, dict):
        if name in obj:
            return obj[name]
        return obj.get(re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower())
    if hasattr(obj, name):
        return getattr(obj, name)
    # P2-1: thiếu cả 2 shape → None an toàn (UI hiển thị "—") thay vì 502
    return getattr(obj, re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower(), None)

def kaggle_quota_payload() -> dict:
    """KaggleApi.quota_view() → {gpu|tpu: {used_s, total_s, remaining_s, refresh}}.

    ImportError → 503; lỗi Kaggle API/khớp shape → 502.
    """
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        raise HTTPException(status_code=503, detail="kaggle package not installed")
    try:
        api = KaggleApi()
        api.authenticate()
        resp = api.quota_view()
        refresh_raw = _field(resp, "quotaRefreshTime")
        refresh = str(refresh_raw) if refresh_raw is not None else None
        out: dict = {}
        for key in ("gpu", "tpu"):
            q = _field(resp, f"{key}Quota")
            used = _seconds(_field(q, "timeUsed"))
            total = _seconds(_field(q, "totalTimeAllowed"))
            out[key] = {
                "used_s": used,
                "total_s": total,
                "remaining_s": max(total - used, 0.0),
                "refresh": refresh,
            }
        return out
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("kaggle quota_view failed: %r", exc)
        raise HTTPException(status_code=502, detail="Kaggle API lỗi, thử lại sau")

def quota_remaining_seconds(api) -> float | None:
    """GPU quota còn lại (giây) trên api đã authenticate — orchestrator
    dispatch gate (AC6). None = không xác định được (lỗi API/shape) →
    caller skip spawn an toàn (không raise)."""
    try:
        resp = api.quota_view()
        q = _field(resp, "gpuQuota")
        used = _seconds(_field(q, "timeUsed"))
        total = _seconds(_field(q, "totalTimeAllowed"))
        return max(total - used, 0.0)
    except Exception as exc:
        logger.warning("kaggle quota_remaining failed: %r", exc)
        return None
