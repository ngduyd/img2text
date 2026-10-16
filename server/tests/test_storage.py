"""Task 1: S3/R2 storage driver tests against moto."""

import urllib.parse

import boto3
import pytest
from moto import mock_aws

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

async def test_put_exists_presign_delete(storage):
    await storage.put("uploads/abc.jpg", b"img")
    assert await storage.exists("uploads/abc.jpg")
    url = await storage.presign_get("uploads/abc.jpg", expires=3600)
    assert "uploads/abc.jpg" in url and "X-Amz-Expires=3600" in url
    await storage.delete_prefix("uploads/")
    assert not await storage.exists("uploads/abc.jpg")

async def test_presign_url_uses_path_style_addressing(storage):
    """Path-style (bucket in path, not host): required for MinIO dev
    localhost endpoints; R2 accepts path-style, so dev/prod share one config."""
    await storage.put("uploads/abc.jpg", b"img")
    url = await storage.presign_get("uploads/abc.jpg", expires=3600)
    parsed = urllib.parse.urlparse(url)
    # no bucket subdomain; bucket appears only in the path
    assert parsed.path == f"/{storage.bucket}/uploads/abc.jpg"
    assert not parsed.hostname.startswith(f"{storage.bucket}.")
    assert url.startswith("https://")

# --- #10 (spec 2026-10-15): Range GET ---

async def test_get_range_returns_exact_slice(storage):
    content = bytes(range(100))  # 100 bytes
    await storage.put("uploads/range.bin", content)
    chunk = await storage.get_range("uploads/range.bin", 10, 19)
    assert len(chunk) == 10
    assert chunk == content[10:20]

async def test_get_range_out_of_bounds_raises(storage):
    await storage.put("uploads/range.bin", b"x" * 100)
    with pytest.raises(ValueError, match="range"):
        await storage.get_range("uploads/range.bin", 100, 200)

async def test_get_range_end_clamps_to_object_size(storage):
    """S3 semantics: end vượt size clamp về byte cuối (không lỗi)."""
    content = b"y" * 100
    await storage.put("uploads/range.bin", content)
    chunk = await storage.get_range("uploads/range.bin", 90, 500)
    assert chunk == content[90:]
