"""Presign HEIC/HEIF/AVIF (spec 2026-10-13 §9b): 200 + storage_key đúng
đuôi, content_type map chuẩn image/heic|heif|avif."""

import io

async def test_presign_heic_heif_avif_200(auth_client):
    from PIL import Image

    import pillow_heif

    pillow_heif.register_heif_opener()
    from tests.test_presign_upload import _presign_body

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="HEIF")
    heif_bytes = buf.getvalue()
    for ext, ctype in (
        ("heic", "image/heic"),
        ("heif", "image/heif"),
        ("avif", "image/avif"),
    ):
        r = await auth_client.post(
            "/api/jobs/presign",
            json=_presign_body(
                data=heif_bytes, filename=f"anh.{ext}", content_type=ctype
            ),
        )
        assert r.status_code == 200, r.text
        assert r.json()["storage_key"].endswith(f".{ext}")
