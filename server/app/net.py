"""Network helpers shared by auth limiter and Task 7 middleware (Ruling R5)."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """Rightmost X-Forwarded-For entry if present, else client host.

    Nearest trusted proxy APPENDS the real client ($proxy_add_forwarded_for
    in nginx), so the rightmost entry is the one we can trust; taking the
    leftmost lets a client prepend its own entry and forge its limiter key
    and request_logs.ip."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host
