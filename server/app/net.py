"""Network helpers shared by auth limiter and Task 7 middleware (Ruling R5)."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """First X-Forwarded-For value (stripped) if present, else client host."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host
