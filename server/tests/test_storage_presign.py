"""F1: S3Driver.presign_post policy (content-length-range, key, expiry,
content-type) + config endpoint auto-build từ R2_ACCOUNT_ID."""

import base64
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3
import pytest
from moto import mock_aws

from app.core.config import Settings
from app.services.storage import S3Driver

MAX_BYTES = 50 * 1024 * 1024

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

def _policy(fields: dict) -> dict:
    return json.loads(base64.b64decode(fields["policy"]))

async def test_presign_post_policy(storage):
    out = await storage.presign_post(
        key="uploads/a.pdf",
        expires=3600,
        max_bytes=MAX_BYTES,
        content_type="application/pdf",
    )
    fields, policy = out["fields"], _policy(out["fields"])
    # cap: browser upload vượt 50MB bị S3 từ chối (policy-side)
    assert ["content-length-range", 0, MAX_BYTES] in policy["conditions"]
    # key pinned + content-type enforced (field + condition phải khớp nhau)
    assert {"key": "uploads/a.pdf"} in policy["conditions"]
    assert ["eq", "$Content-Type", "application/pdf"] in policy["conditions"]
    assert fields["key"] == "uploads/a.pdf"
    assert fields["Content-Type"] == "application/pdf"
    assert "x-amz-signature" in fields

async def test_presign_post_expiry(storage):
    out = await storage.presign_post(
        key="uploads/a.jpg",
        expires=3600,
        max_bytes=MAX_BYTES,
        content_type="image/jpeg",
    )
    exp = datetime.fromisoformat(
        _policy(out["fields"])["expiration"].replace("Z", "+00:00")
    )
    delta = (exp - datetime.now(timezone.utc)).total_seconds()
    assert 3500 <= delta <= 3600

async def test_presign_post_url_path_style(storage):
    """Path-style upload URL (dev MinIO/localstack); R2 accepts path-style."""
    out = await storage.presign_post(
        key="uploads/a.jpg",
        expires=60,
        max_bytes=MAX_BYTES,
        content_type="image/jpeg",
    )
    parsed = urlparse(out["url"])
    assert parsed.path == f"/{storage.bucket}"
    assert not parsed.hostname.startswith(f"{storage.bucket}.")

def test_r2_endpoint_auto_builds_from_account_id():
    s = Settings(r2_endpoint="", r2_account_id="acct123")
    assert s.r2_endpoint_url == "https://acct123.r2.cloudflarestorage.com"

def test_r2_endpoint_explicit_wins():
    s = Settings(r2_endpoint="http://localhost:4566", r2_account_id="acct123")
    assert s.r2_endpoint_url == "http://localhost:4566"

def test_r2_endpoint_empty_without_account_id():
    assert Settings(r2_endpoint="", r2_account_id="").r2_endpoint_url == ""
