"""Network helpers shared by auth limiter and Task 7 middleware (Ruling R5)."""

import ipaddress
import logging
from functools import lru_cache

from fastapi import Request

from app.core.config import settings

logger = logging.getLogger(__name__)

# Dải proxy mặc định: loopback + mạng riêng của Docker/k8s. Nginx trong compose
# gọi server qua IP nội bộ 172.x, nên chỉ những peer này mới đáng tin để đọc XFF.
_DEFAULT_TRUSTED = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

@lru_cache(maxsize=8)
def _trusted(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("trusted_proxies: bỏ qua mục không hợp lệ %r", part)
    return tuple(nets)

def _is_trusted_proxy(host: str | None) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    raw = settings.trusted_proxies or _DEFAULT_TRUSTED
    return any(addr in net for net in _trusted(raw))

def client_ip(request: Request) -> str:
    """IP client thật: X-Forwarded-For CHỈ khi request đến từ proxy tin cậy.

    Nearest trusted proxy APPENDS the real client ($proxy_add_forwarded_for
    trong nginx) nên entry phải-nhất là entry đáng tin; lấy trái-nhất thì client
    tự chèn được. Nhưng nếu peer KHÔNG phải proxy (API expose trực tiếp) thì
    XFF do client tự đặt → mỗi request một IP giả sẽ vô hiệu toàn bộ rate limit.
    """
    peer = request.client.host if request.client else None
    if _is_trusted_proxy(peer):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return peer or "unknown"
