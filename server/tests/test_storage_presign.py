"""F1: S3Driver.presign_put URL (key pinned, expiry, path-style — R2
PostObject 501 → PUT) + config endpoint auto-build từ R2_ACCOUNT_ID."""

from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from moto import mock_aws

from app.core.config import Settings
from app.services.storage import S3Driver


@pytest.fixture
def storage():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket="img2text-test"
        )
        yield S3Driver(
            endpoint=None,
            key_id="test-key",
            secret="test-secret",
            bucket="img2text-test",
            region="us-east-1",
        )

def _expires(url: str) -> int:
    return int(parse_qs(urlparse(url).query)["X-Amz-Expires"][0])

async def test_presign_put_url_pins_key(storage):
    out = await storage.presign_put(key="uploads/a.pdf", expires=3600)
    parsed = urlparse(out)
    assert parsed.path.endswith("/uploads/a.pdf")
    assert "X-Amz-Signature" in parse_qs(parsed.query)

async def test_presign_put_expiry(storage):
    out = await storage.presign_put(key="uploads/a.jpg", expires=3600)
    assert _expires(out) == 3600

async def test_presign_put_url_path_style(storage):
    """Path-style upload URL (dev MinIO/localstack); R2 accepts path-style."""
    out = await storage.presign_put(key="uploads/a.jpg", expires=60)
    parsed = urlparse(out)
    assert parsed.path == f"/{storage.bucket}/uploads/a.jpg"
    assert not parsed.hostname.startswith(f"{storage.bucket}.")

def test_r2_endpoint_auto_builds_from_account_id():
    s = Settings(r2_endpoint="", r2_account_id="acct123")
    assert s.r2_endpoint_url == "https://acct123.r2.cloudflarestorage.com"

def test_r2_endpoint_explicit_wins():
    s = Settings(r2_endpoint="http://localhost:4566", r2_account_id="acct123")
    assert s.r2_endpoint_url == "http://localhost:4566"

def test_r2_endpoint_empty_without_account_id():
    assert Settings(r2_endpoint="", r2_account_id="").r2_endpoint_url == ""
