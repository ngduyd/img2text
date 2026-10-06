"""Split storage endpoint (dev upload 500 hotfix): ops client vs presign client.

Ops calls (put/exists/head) go to the INTERNAL endpoint (in-network
localstack in dev); presigned URLs are fetched by the USER'S BROWSER and
must be signed with the PUBLIC endpoint (host-reachable localhost:4566).
"""

from urllib.parse import urlparse

from app.core.config import settings
from app.services.storage import S3Driver, build_storage

def _driver(**kw):
    base = dict(
        endpoint="http://internal:4566",
        key_id="k",
        secret="s",
        bucket="b",
        region="us-east-1",
    )
    base.update(kw)
    return S3Driver(**base)

def test_public_empty_presign_client_falls_back_to_ops(monkeypatch):
    monkeypatch.setattr(settings, "r2_endpoint", "http://internal:4566")
    monkeypatch.setattr(settings, "storage_public_endpoint", "")
    d = build_storage()
    assert d.client.meta.endpoint_url == "http://internal:4566"
    assert d.presign_client.meta.endpoint_url == "http://internal:4566"

def test_public_set_presign_client_uses_public_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "r2_endpoint", "http://internal:4566")
    monkeypatch.setattr(settings, "storage_public_endpoint", "http://localhost:4566")
    d = build_storage()
    # ops client stays internal; presign client is a SEPARATE client on public
    assert d.client.meta.endpoint_url == "http://internal:4566"
    assert d.presign_client.meta.endpoint_url == "http://localhost:4566"
    assert d.presign_client is not d.client

async def test_presign_get_signed_by_public_client():
    d = _driver(public_endpoint="http://localhost:4566")
    url = await d.presign_get("uploads/x.jpg", expires=3600)
    # netloc comes from the presign client's endpoint_url — proof
    # presign_get used the PUBLIC client, not the ops client
    assert urlparse(url).netloc == "localhost:4566"

def test_single_endpoint_prod_unchanged():
    """Empty public endpoint + empty ops endpoint (prod R2): one client."""
    d = _driver(endpoint="", public_endpoint="")
    # empty endpoint_url → botocore default AWS S3 endpoint; ONE client covers both
    assert d.presign_client is d.client
    assert d.client.meta.endpoint_url.endswith("amazonaws.com")
