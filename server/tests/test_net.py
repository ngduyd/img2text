"""client_ip: X-Forwarded-For trust (rightmost entry) + fallback."""

from starlette.requests import Request

from app.core.net import client_ip


def _request(xff: str | None) -> Request:
    headers = [] if xff is None else [(b"x-forwarded-for", xff.encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": headers,
            "client": ("10.0.0.9", 1234),
        }
    )


def test_client_ip_takes_rightmost_xff():
    # nearest trusted proxy appends real client; leftmost is client-controlled
    assert client_ip(_request("203.0.113.1, 198.51.100.7")) == "198.51.100.7"


def test_client_ip_single_entry():
    assert client_ip(_request("203.0.113.1")) == "203.0.113.1"


def test_client_ip_falls_back_to_client_host():
    assert client_ip(_request(None)) == "10.0.0.9"
