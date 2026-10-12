"""Presign chấp nhận alias ``image/jpg`` (browser không chuẩn trên Android/
Windows report ``.jpg`` là ``image/jpg``) — chuẩn hóa về ``image/jpeg``."""


async def test_presign_accepts_image_jpg_alias(auth_client):
    from tests.conftest import TEST_JPEG
    from tests.test_presign_upload import _presign_body

    # canonical map luôn image/jpeg; alias image/jpg phải map về đây
    from app.routers.jobs import CONTENT_TYPE_BY_EXT

    assert CONTENT_TYPE_BY_EXT["jpg"] == "image/jpeg"

    body = _presign_body(
        data=TEST_JPEG,
        filename="anh.jpg",
        content_type="image/jpg",
    )
    r = await auth_client.post("/api/jobs/presign", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["storage_key"].endswith(".jpg")


async def test_presign_still_rejects_mismatch_after_alias(auth_client):
    """Alias không nới lỏng: .png + image/jpg vẫn 422."""
    from tests.test_presign_upload import _presign_body

    body = _presign_body(filename="x.png", content_type="image/jpg")
    r = await auth_client.post("/api/jobs/presign", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == "Định dạng file không được hỗ trợ."
