"""Save text phẳng ở Overview → regions (giữ thứ tự + anchor ảnh) → rebuild layout.

Bug gốc (2026-11-07, job #84): `result.extraction_text` sửa tay còn layout render
từ `result.pages[].regions[].text` → sửa text không bao giờ tới md-layout/docx-layout.
Đường cũ chỉ sync khi client gửi old_phrase/new_phrase; Save full text không gửi
→ layout đứng im, nút "đồng bộ" render lại y hệt.
"""

from app.services.layout_sync import apply_text_to_regions


def _result(regions, markdown="# tài liệu"):
    return {
        "markdown": markdown,
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "regions": regions,
            }
        ],
    }


def _region(rid, text, bbox=(1, 2, 30, 40), placeholder=False):
    return {
        "id": rid,
        "bbox": list(bbox),
        "text": text,
        "verdict": "image_unextractable" if placeholder else "ok",
        "placeholder": placeholder,
    }


def test_edit_hits_owning_region_only():
    result = _result(
        [
            _region("r0", "DE KIEM TRA"),
            _region("r1", "Cau 1. Cho phuong trinh"),
            _region("r2", "", bbox=(5, 6, 70, 80), placeholder=True),
        ]
    )
    old = "DE KIEM TRA\nCau 1. Cho phuong trinh\n"
    assert apply_text_to_regions(result, "DE KIEM TRA\nCau 1. Cho phuong trinh x^2") is True
    regions = result["pages"][0]["regions"]
    assert regions[0]["text"] == "DE KIEM TRA"
    assert regions[1]["text"] == "Cau 1. Cho phuong trinh x^2"
    # vùng ảnh không bị đụng
    assert regions[2]["text"] == ""
    assert regions[2]["placeholder"] is True
    assert old  # sanity: text cũ đúng thứ tự đã dùng để diff


def test_inserted_line_lands_in_owning_region():
    result = _result([_region("r0", "Mot"), _region("r1", "Hai")])
    apply_text_to_regions(result, "Mot\nDong chen\nHai")
    assert result["pages"][0]["regions"][0]["text"] == "Mot\nDong chen"
    assert result["pages"][0]["regions"][1]["text"] == "Hai"


def test_deleted_line_empties_region_without_losing_others():
    result = _result([_region("r0", "Mot"), _region("r1", "Hai")])
    apply_text_to_regions(result, "Hai")
    assert result["pages"][0]["regions"][0]["text"] == ""
    assert result["pages"][0]["regions"][1]["text"] == "Hai"


def test_new_lines_at_end_append_to_last_region():
    result = _result([_region("r0", "Mot")])
    apply_text_to_regions(result, "Mot\nThem")
    assert result["pages"][0]["regions"][0]["text"] == "Mot\nThem"


def test_no_regions_is_noop():
    result = {"markdown": "x", "pages": []}
    assert apply_text_to_regions(result, "bat ky") is False
    assert result == {"markdown": "x", "pages": []}


async def test_full_text_save_rebuilds_layout(
    auth_client, app, storage, done_job_with_result
):
    """Save full text (không old/new phrase) → md-layout render lại từ text mới."""
    jid = done_job_with_result
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "Xin chào bạn", "expected_text_version": 0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text_version"] == 1

    md = (await storage.get(f"exports/{jid}/md-layout")).decode("utf-8")
    assert "Xin chào bạn" in md

    job = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert job["stale_layouts"] == []


async def test_rebuild_records_head_version_so_layout_not_stale(
    auth_client, app, storage, done_job_with_result
):
    """Đã có row version cũ (based_on 0) → Save text phải đánh dấu head mới là
    dựa trên text_version mới, nếu không badge "cần đồng bộ" treo mãi."""
    from app.services.doc_versions import save_version

    jid = done_job_with_result
    await storage.put(f"exports/{jid}/md-layout", b"# tieu de cu")
    await save_version(storage, jid, "md-layout", b"# tieu de cu", 0)

    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "Xin chào bạn", "expected_text_version": 0},
    )
    assert r.status_code == 200, r.text
    job = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert job["stale_layouts"] == []
    versions = (await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")).json()
    assert versions["items"][0]["based_on_text_version"] == job["text_version"]


def test_inserted_line_at_top_goes_to_first_region():
    """Chèn dòng ở đầu văn bản không được nuốt mất text (owner_at(-1) = None)."""
    result = _result([_region("r0", "Mot"), _region("r1", "Hai")])
    apply_text_to_regions(result, "Khong\nMot\nHai")
    assert result["pages"][0]["regions"][0]["text"] == "Khong\nMot"
    assert result["pages"][0]["regions"][1]["text"] == "Hai"


def test_rewrite_across_two_regions_stays_proportional():
    """Viết lại cả đoạn trải 2 region (2 dòng mỗi region) → vẫn 2/2, không dồn
    hết vào region đầu (giữ hình dạng để ảnh/bảng cạnh đó không lệch)."""
    result = _result(
        [
            _region("r0", "A1\nA2"),
            _region("r1", "B1\nB2"),
        ]
    )
    apply_text_to_regions(result, "A1 sua\nA2 sua\nB1 sua\nB2 sua")
    assert result["pages"][0]["regions"][0]["text"] == "A1 sua\nA2 sua"
    assert result["pages"][0]["regions"][1]["text"] == "B1 sua\nB2 sua"


def _bbox_region(rid, text, y0, y1):
    return {
        "id": rid,
        "bbox": [10, y0, 300, y1],
        "text": text,
        "verdict": "ok",
        "placeholder": False,
    }


def test_rewrite_distributed_by_bbox_height_not_line_count():
    """Neo theo BBOX: 3 region, mỗi region 5 dòng cũ nhưng cao 100/400/50 px →
    đoạn viết lại 20 dòng chia theo chiều cao (4/15/1), không chia đều 5/5/5."""
    result = _result(
        [
            _bbox_region("r0", "\n".join(f"a{i}" for i in range(5)), 0, 100),
            _bbox_region("r1", "\n".join(f"b{i}" for i in range(5)), 100, 500),
            _bbox_region("r2", "\n".join(f"c{i}" for i in range(5)), 500, 550),
        ]
    )
    new_text = "\n".join(f"n{i}" for i in range(20))
    apply_text_to_regions(result, new_text)
    got = [len(r["text"].split("\n")) if r["text"] else 0 for r in result["pages"][0]["regions"]]
    assert got == [4, 15, 1]
    # thứ tự dòng giữ nguyên toàn văn
    joined = "\n".join(r["text"] for r in result["pages"][0]["regions"])
    assert joined == new_text


def test_missing_bbox_falls_back_to_line_count():
    result = _result([_region("r0", "A1\nA2"), _region("r1", "B1\nB2")])
    for r in result["pages"][0]["regions"]:
        r["bbox"] = None
    apply_text_to_regions(result, "n1\nn2\nn3\nn4")
    assert result["pages"][0]["regions"][0]["text"] == "n1\nn2"
    assert result["pages"][0]["regions"][1]["text"] == "n3\nn4"


# --- thứ tự đọc theo cột + neo chữ mới theo vị trí (2026-11-07) ---

def _two_col_result():
    """Trang 2 cột: mảng region theo hàng (y rồi x), thứ tự ĐỌC là hết cột trái."""
    return _result(
        [
            _region("a1", "A", bbox=(100, 100, 500, 200)),
            _region("b1", "B", bbox=(520, 100, 900, 200)),
            _region("a2", "C", bbox=(100, 210, 500, 300)),
            _region("b2", "D", bbox=(520, 210, 900, 300)),
        ]
    )


def test_text_from_regions_uses_reading_order():
    """Text người dùng thấy phải cùng thứ tự với layout: hết cột trái rồi cột phải."""
    from app.services.layout_sync import text_from_regions

    assert text_from_regions(_two_col_result()) == "A\nC\nB\nD"


def test_edit_in_reading_order_text_hits_right_region():
    from app.services.layout_sync import apply_text_to_regions, text_from_regions

    result = _two_col_result()
    result["extraction_text"] = text_from_regions(result)
    apply_text_to_regions(result, "A\nC\nB sua\nD")
    texts = {r["id"]: r["text"] for r in result["pages"][0]["regions"]}
    assert texts == {"a1": "A", "b1": "B sua", "a2": "C", "b2": "D"}


def test_legacy_row_major_text_still_maps_by_content():
    """Row cũ (chưa migrate) lưu text theo hàng A/B/C/D → vẫn neo đúng region."""
    from app.services.layout_sync import apply_text_to_regions

    result = _two_col_result()
    result["extraction_text"] = "A\nB\nC\nD"
    apply_text_to_regions(result, "A\nB sua\nC\nD")
    texts = {r["id"]: r["text"] for r in result["pages"][0]["regions"]}
    assert texts == {"a1": "A", "b1": "B sua", "a2": "C", "b2": "D"}


def test_new_text_above_image_stays_above_image():
    """Xoá chữ dưới ảnh, gõ chữ mới NGAY DƯỚI tiêu đề (trên ảnh) → chữ phải ở
    region TRÊN ảnh, không bị đẩy xuống region dưới ảnh."""
    from app.services.layout_sync import apply_text_to_regions, text_from_regions

    result = _result(
        [
            _region("r1", "Tieu de", bbox=(10, 0, 300, 100)),
            _region("img", "", bbox=(10, 100, 300, 400), placeholder=True),
            _region("r2", "Ket luan", bbox=(10, 400, 300, 500)),
        ]
    )
    result["extraction_text"] = text_from_regions(result)
    assert result["extraction_text"] == "Tieu de\n\nKet luan"
    apply_text_to_regions(result, "Tieu de\ndong moi 1\ndong moi 2")
    texts = {r["id"]: r["text"] for r in result["pages"][0]["regions"]}
    assert texts["r1"] == "Tieu de\ndong moi 1\ndong moi 2"
    assert texts["r2"] == ""
    assert texts["img"] == ""
