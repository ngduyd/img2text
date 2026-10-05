"""S3/R2 object storage driver (Task 1).

R2 speaks the S3 API; `r2_region` defaults to "auto" (R2's fixed region).
All boto3 calls run via asyncio.to_thread — boto3 is synchronous.
"""

import asyncio
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import Request

from app.config import settings

class StorageDriver(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def presign_get(self, key: str, expires: int) -> str: ...
    async def exists(self, key: str) -> bool: ...
    async def get(self, key: str) -> bytes: ...
    async def delete_prefix(self, prefix: str) -> None: ...

class S3Driver:
    def __init__(
        self,
        endpoint: str,
        key_id: str,
        secret: str,
        bucket: str,
        region: str,
    ) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=key_id or None,
            aws_secret_access_key=secret or None,
            region_name=region,
            # R2 requires SigV4; botocore defaults us-east-1 S3 to legacy sigv2.
            # path-style addressing: MinIO (dev storage, localhost endpoints)
            # breaks with AWS-style virtual-host addressing; R2 accepts
            # path-style too, so one config covers both dev and prod.
            config=Config(
                signature_version="s3v4", s3={"addressing_style": "path"}
            ),
        )

    async def put(self, key: str, data: bytes) -> None:
        # dedupe: content-addressed key already stored = no-op
        if await self.exists(key):
            return
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key, Body=data
        )

    async def presign_get(self, key: str, expires: int) -> str:
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError as e:
                if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise

        return await asyncio.to_thread(_head)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            try:
                resp = self.client.get_object(Bucket=self.bucket, Key=key)
                return resp["Body"].read()
            except ClientError as e:
                # ruling R24: missing key raises KeyError so callers can 404
                if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                    raise KeyError(key) from e
                raise

        return await asyncio.to_thread(_get)

    async def delete_prefix(self, prefix: str) -> None:
        def _delete() -> None:
            for page in self.client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                keys = [{"Key": o["Key"]} for o in page.get("Contents") or []]
                if keys:
                    resp = self.client.delete_objects(
                        Bucket=self.bucket, Delete={"Objects": keys}
                    )
                    # delete_objects reports per-key failures in-body, no raise
                    errors = resp.get("Errors") or []
                    if errors:
                        raise RuntimeError(
                            f"S3 delete_objects failed: {errors!r:.400}"
                        )

        await asyncio.to_thread(_delete)

def get_storage(request: Request) -> StorageDriver:
    """FastAPI DI: routers use Depends(get_storage); tests inject
    app.state.storage (create_app wires the real driver)."""
    return request.app.state.storage

def build_storage() -> S3Driver:
    """Driver from current settings (create_app wiring helper)."""
    return S3Driver(
        settings.r2_endpoint,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket,
        settings.r2_region,
    )
