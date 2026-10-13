"""Kernel unit tests (spec 2026-10-09 batch one-run + spec 2026-10-10 F3
manifest dual-mode: fetch_input download + sha256 verify, load_manifest,
mount fallback). find_inputs parses the
{job_id}__ staging prefix (sorted, dirs/unknown ext/non-prefixed skipped with
a log); run_batch continues past a failing job and sets the exit code from
outputs written. The module is imported DIRECTLY (import stays stdlib-only —
the pip/apt/venv bootstrap + heavy deps run only as __main__), no Kaggle."""

import functools
import hashlib
import http.server
import json
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "deploy" / "kaggle" / "kernel"))

import img2text_batch as kb  # noqa: E402


def test_find_inputs_parses_job_prefix_sorted_and_skips(tmp_path, capsys):
    (tmp_path / "5__b.png").write_bytes(b"x")
    (tmp_path / "3__a.pdf").write_bytes(b"x")
    (tmp_path / "10__c.jpg").write_bytes(b"x")
    sub = tmp_path / "owner" / "img2text-input"  # Kaggle nests mounts
    sub.mkdir(parents=True)
    (sub / "9__nested.png").write_bytes(b"x")
    (tmp_path / "noprefix.png").write_bytes(b"x")  # no {id}__ → skip + log
    (tmp_path / "abc__bad.png").write_bytes(b"x")  # non-numeric → skip
    (tmp_path / "dataset-metadata.json").write_text("{}")  # unknown ext → skip
    (tmp_path / "7__dir").mkdir()  # directory → skip
    got = kb.find_inputs(str(tmp_path))
    assert [job_id for job_id, _ in got] == [3, 5, 9, 10]  # NUMERIC sort
    assert all(Path(p).is_file() for _, p in got)
    assert "noprefix.png" in capsys.readouterr().out  # skip is logged


def test_process_job_param_does_not_shadow_preprocess_fn():
    """Version 20 'NoneType' object is not callable: param `preprocess` của
    process_job shadow module fn preprocess(path, out_path) → dòng
    pre_info[name] = preprocess(p, ...) gọi None (đúng NoneType callable)."""
    import inspect

    assert callable(kb.preprocess)
    assert "preprocess" not in inspect.signature(kb.process_job).parameters

def test_find_inputs_empty_root_returns_empty(tmp_path):
    assert kb.find_inputs(str(tmp_path)) == []


def test_run_batch_continues_past_failing_job_and_exit_codes(monkeypatch):
    ok: list[int] = []

    def _ok(job_id, path, preprocess=None):
        ok.append(job_id)

    def _boom(job_id, path, preprocess=None):
        raise SystemExit("OCR phase exited 1 — xem log ở trên")

    def _only_job2_boom(job_id, path, preprocess=None):
        if job_id == 2:
            _boom(job_id, path)
        ok.append(job_id)

    monkeypatch.setattr(kb, "process_job", _ok)
    # every job processed → exit 0
    assert kb.run_batch([(1, "a", None), (2, "b", None), (3, "c", None)]) == 0
    assert ok == [1, 2, 3]

    # job 2's error must NOT stop jobs 1/3 (continue-on-error) → still exit 0
    ok.clear()
    monkeypatch.setattr(kb, "process_job", _only_job2_boom)
    assert kb.run_batch([(1, "a", None), (2, "b", None), (3, "c", None)]) == 0
    assert ok == [1, 3]

    # zero outputs written → exit 1
    monkeypatch.setattr(kb, "process_job", _boom)
    assert kb.run_batch([(9, "x", None)]) == 1

# --- F3 (spec 2026-10-10): manifest dual-mode — URL download + sha256
# verify / mount fallback. Local http.server = offline unit, no network. ---

@pytest.fixture
def served_file(tmp_path):
    payload = b"%PDF-1.4 fake bytes"
    (tmp_path / "doc.pdf").write_bytes(payload)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", payload
    server.shutdown()

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def test_fetch_input_downloads_and_verifies_sha256(served_file, tmp_path):
    base, payload = served_file
    dest = tmp_path / "dl" / "1__doc.pdf"  # parent dir chưa có → fetch tạo
    kb.fetch_input(f"{base}/doc.pdf", str(dest), _sha(payload))
    assert dest.read_bytes() == payload

def test_fetch_input_sha256_mismatch_removes_dest(served_file, tmp_path):
    base, _ = served_file
    dest = tmp_path / "2__doc.pdf"
    with pytest.raises(RuntimeError):
        kb.fetch_input(f"{base}/doc.pdf", str(dest), "0" * 64)
    assert not dest.exists()

def test_fetch_input_aborts_oversize_stream(tmp_path, monkeypatch):
    """R2: streaming size cap — >50MB mid-stream → dest removed + raise
    (the presigned content-length-range spirit, enforced client-side too)."""
    import urllib.request

    class _Resp:  # infinite 1MB chunks — only the cap can stop it
        def read(self, n):
            return b"x" * n

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    dest = tmp_path / "big.pdf"
    with pytest.raises(RuntimeError, match="quá 50MB"):
        kb.fetch_input("http://x/big.pdf", str(dest))
    assert not dest.exists()

def test_default_pdftoppm_page_cap_skips_rasterize(monkeypatch):
    """R2 P1 DoS: real page count > MAX_PDF_PAGES → raise BEFORE any
    get_pixmap (client page_count untrusted)."""
    fake = types.ModuleType("fitz")

    class _Doc:
        page_count = kb.MAX_PDF_PAGES + 1

        def __iter__(self):
            for _ in range(self.page_count):
                page = types.SimpleNamespace()
                page.get_pixmap = lambda dpi=0: (_ for _ in ()).throw(
                    AssertionError("must not rasterize past the cap")
                )
                yield page

    fake.open = lambda **kw: _Doc()
    monkeypatch.setitem(sys.modules, "fitz", fake)
    with pytest.raises(RuntimeError, match=f"quá {kb.MAX_PDF_PAGES}"):
        kb.default_pdftoppm(b"%PDF-fake", "pdf")

def test_load_manifest_malformed_falls_back_to_mount(tmp_path):
    """R2: malformed manifest (non-dict root / jobs not list-of-dict) →
    None = mount fallback, never a batch crash."""
    mount = tmp_path / "input"
    mount.mkdir()
    manifest = mount / "manifest.json"
    for bad in ('{"jobs": "nope"}', "[]", '{"jobs": [{"job_id": 1}, "junk"]}'):
        manifest.write_text(bad, encoding="utf-8")
        assert kb.load_manifest(str(mount)) is None, bad
    manifest.write_text('{"jobs": [{"job_id": 1}]}', encoding="utf-8")
    assert kb.load_manifest(str(mount)) == [{"job_id": 1}]

def test_fetch_input_http_error_raises(tmp_path):
    with pytest.raises(Exception):
        kb.fetch_input(
            "http://127.0.0.1:9/missing.pdf", str(tmp_path / "x.pdf"), None, timeout=2
        )

def test_manifest_dual_mode_downloads_and_falls_back_to_mount(served_file, tmp_path):
    base, payload = served_file
    mount = tmp_path / "input"
    mount.mkdir()
    (mount / "9__legacy.pdf").write_bytes(b"legacy")  # dev mount fallback
    jobs = [
        {"job_id": 1, "input_url": f"{base}/doc.pdf", "filename": "1__doc.pdf",
         "sha256": _sha(payload)},                      # URL mode
        {"job_id": 2, "input_url": f"{base}/missing.pdf", "filename": "2__x.pdf",
         "sha256": None},                               # 404 → không fallback → bỏ qua
        {"job_id": 9, "input_url": f"{base}/missing.pdf", "filename": "9__x.pdf",
         "sha256": None},                               # 404 → mount fallback
    ]
    (mount / "manifest.json").write_text(json.dumps({"jobs": jobs}))
    assert kb.load_manifest(str(mount)) == jobs
    got = kb.fetch_manifest_jobs(jobs, str(tmp_path / "dl"), root=str(mount))
    assert [job_id for job_id, _path, _pp in got] == [1, 9]
    assert Path(got[0][1]).read_bytes() == payload  # download + verify
    assert got[1][1].endswith("9__legacy.pdf")      # mount fallback

def test_no_manifest_is_mount_fallback_mode(tmp_path):
    (tmp_path / "5__a.pdf").write_bytes(b"x")
    assert kb.load_manifest(str(tmp_path)) is None
    assert kb.find_inputs(str(tmp_path)) == [(5, str(tmp_path / "5__a.pdf"))]

# --- wave-2 #4 (spec 2026-10-14): manifest preprocess → pipeline ---

def test_fetch_manifest_jobs_reads_preprocess(served_file, tmp_path):
    base, payload = served_file
    pp = {"pages": [1, 3], "rotate": {"1": 90}}
    jobs = [
        {"job_id": 1, "input_url": f"{base}/doc.pdf", "filename": "1__doc.pdf",
         "sha256": _sha(payload), "preprocess": pp},
        {"job_id": 2, "input_url": f"{base}/doc.pdf", "filename": "2__doc.pdf",
         "sha256": _sha(payload)},  # thiếu key → None
    ]
    got = kb.fetch_manifest_jobs(jobs, str(tmp_path / "dl"))
    assert got[0] == (1, str(tmp_path / "dl" / "1__doc.pdf"), pp)
    assert got[1] == (2, str(tmp_path / "dl" / "2__doc.pdf"), None)

def test_run_batch_passes_preprocess_to_process_job(monkeypatch):
    seen = []
    def _capture(job_id, path, preprocess=None):
        seen.append((job_id, path, preprocess))
    monkeypatch.setattr(kb, "process_job", _capture)
    pp = {"pages": [1, 3], "rotate": {"1": 90}}
    assert kb.run_batch([(1, "a", pp), (2, "b", None)]) == 0
    assert seen == [(1, "a", pp), (2, "b", None)]

def test_apply_preprocess_select_and_rotate(tmp_path):
    """Chọn trang + xoay (worker loop pattern, file-based; R55 giữ tên trang)."""
    from PIL import Image
    paths = []
    for n in (1, 2, 3):
        p = tmp_path / f"page_{n:04d}.png"
        Image.new("RGB", (4, 2)).save(p, "PNG")
        paths.append(str(p))
    out = kb._apply_preprocess(paths, {"pages": [1, 3], "rotate": {"3": 90}})
    assert [Path(p).name for p in out] == ["page_0001.png", "page_0003.png"]
    assert not Path(paths[1]).exists()        # trang 2 không được chọn → loại
    assert Image.open(out[1]).size == (2, 4)  # 90° CW → swap w/h
    # None → giữ nguyên (không lọc, không xoay)
    lone = tmp_path / "page_0009.png"
    Image.new("RGB", (4, 2)).save(lone, "PNG")
    assert kb._apply_preprocess([str(lone)], None) == [str(lone)]
    assert Image.open(lone).size == (4, 2)

def test_apply_preprocess_real_png_select_rotate_closes_handles(tmp_path, monkeypatch):
    """review r1 P1-5: PNG thật 2 trang — page-select + rotate 90 → file lưu
    (size swap) + MỌI Image.open handle được close (`with` trong fix)."""
    from PIL import Image

    opened: list = []
    real_open = Image.open

    class _Spy:
        def __init__(self, fp, *a, **k):
            self._im = real_open(fp, *a, **k)
            self.closed = False
            opened.append(self)

        def transpose(self, op):  # code cũ (chưa `with`) gọi thẳng trên object
            return self._im.transpose(op)

        def __enter__(self):
            return self._im

        def __exit__(self, *exc):
            self._im.close()
            self.closed = True
            return False

    monkeypatch.setattr(Image, "open", lambda fp, *a, **k: _Spy(fp, *a, **k))
    p1, p2 = tmp_path / "page_0001.png", tmp_path / "page_0002.png"
    Image.new("RGB", (20, 10), "blue").save(p1, "PNG")
    Image.new("RGB", (10, 20), "red").save(p2, "PNG")
    out = kb._apply_preprocess(
        [str(p1), str(p2)], {"pages": [1, 2], "rotate": {"2": 90}}
    )
    assert [Path(p).name for p in out] == ["page_0001.png", "page_0002.png"]
    with Image.open(p2) as im:
        assert im.size == (20, 10)  # 90° CW → swap w/h, file đã lưu
    assert p1.exists() and p2.exists()
    assert opened and all(s.closed for s in opened), "Image.open phải đóng (with)"

def test_rasterize_exif_orientation_6_transposed(tmp_path):
    """EXIF-rotate trước OCR (spec §9b): JPEG 100x50 orientation=6 →
    page PNG 50x100 (transpose áp orientation trước khi OCR đọc pixels)."""
    from PIL import Image

    src = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW để hiển thị đúng
    Image.new("RGB", (100, 50), "red").save(src, "JPEG", exif=exif)
    out = kb.rasterize_to_pages(str(src), str(tmp_path / "raw"))
    with Image.open(out[0]) as im:
        assert im.size == (50, 100)

def test_rasterize_heif_input_decodes(tmp_path):
    """review r1 P0-2: kernel nhận .heif/.heic (server cho phép) —
    rasterize register pillow_heif opener; env thiếu lib → skip."""
    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image

    src = tmp_path / "anh.heif"
    # HeifFile.save ghi bytes trực tiếp — KHÔNG register opener vào PIL
    # process test → Image.open chỉ mở được nhờ kernel tự register (RED thật).
    pillow_heif.from_pillow(Image.new("RGB", (8, 8), "red")).save(str(src))
    out = kb.rasterize_to_pages(str(src), str(tmp_path / "raw"))
    assert len(out) == 1
    with Image.open(out[0]) as im:
        assert im.size == (8, 8)

# --- lane H task 1 (OCR perf): downscale jpg/webp quá lớn + scales.json ---

def test_rasterize_downscales_jpg_over_3000_writes_scales(tmp_path):
    """Lane H: jpg phone cao phân giải (max side > 3000) → page PNG max side
    ≤3000 (LANCZOS, giữ tỉ lệ) + scales.json {page_stem: mới/cũ} = 0.75."""
    from PIL import Image

    src = tmp_path / "big.jpg"
    Image.new("RGB", (4000, 3000), "white").save(src, "JPEG", quality=90)
    out = kb.rasterize_to_pages(str(src), str(tmp_path / "raw"))
    with Image.open(out[0]) as im:
        assert im.size == (3000, 2250)  # giữ tỉ lệ, max side = 3000
    scales = json.loads((tmp_path / "scales.json").read_text(encoding="utf-8"))
    assert scales == {"page_0001": 0.75}

def test_rasterize_small_jpg_keeps_size_no_scales(tmp_path):
    """Ảnh nhỏ (max side ≤ 3000) không đổi → scales.json không sinh ra."""
    from PIL import Image

    src = tmp_path / "small.jpg"
    Image.new("RGB", (800, 600), "white").save(src, "JPEG")
    out = kb.rasterize_to_pages(str(src), str(tmp_path / "raw"))
    with Image.open(out[0]) as im:
        assert im.size == (800, 600)
    assert not (tmp_path / "scales.json").exists()

def test_rasterize_pdf_branch_no_downscale_no_scales(tmp_path):
    """PDF branch giữ nguyên (pdftoppm 200dpi) — không downscale, không scales."""
    import fitz

    doc = fitz.open()
    doc.new_page(width=200, height=300).draw_rect(
        fitz.Rect(10, 10, 100, 100), color=(1, 0, 0), fill=(1, 0, 0))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(doc.tobytes())
    doc.close()
    kb.rasterize_to_pages(str(pdf), str(tmp_path / "raw"))
    assert not (tmp_path / "scales.json").exists()

# --- wave-3 (spec 2026-10-13): bảng cells → md GFM pipe + reading order 2 cột ---

FIXTURE_TABLE_HTML = (
    "<table><tr><th>a</th><th>b</th></tr><tr><td>c</td><td>d</td></tr></table>"
)

def test_parse_table_html_two_cols_two_rows_th():
    rows = kb._parse_table_html(FIXTURE_TABLE_HTML)
    assert [[c["text"] for c in r] for r in rows] == [["a", "b"], ["c", "d"]]
    assert [c["header"] for c in rows[0]] == [True, True]
    assert [c["header"] for c in rows[1]] == [False, False]
    assert all(c["rowspan"] == 1 and c["colspan"] == 1 for r in rows for c in r)

def test_parse_table_html_regex_fallback_matches_shape():
    rows = kb._parse_table_regex(FIXTURE_TABLE_HTML)
    assert [[c["text"] for c in r] for r in rows] == [["a", "b"], ["c", "d"]]
    assert [c["header"] for c in rows[0]] == [True, True]

def test_parse_table_html_span_attrs_int_default_one():
    html = '<table><tr><td rowspan="2" colspan="3">x</td><td>y</td></tr></table>'
    (row,) = kb._parse_table_html(html)
    assert (row[0]["rowspan"], row[0]["colspan"]) == (2, 3)
    assert (row[1]["rowspan"], row[1]["colspan"]) == (1, 1)

def test_safe_span_non_numeric_or_nonpositive_defaults_one():
    """P1: rowspan="foo"/"2.0"/None/0 → 1, không ValueError (giết cả job)."""
    assert kb._safe_span("abc") == 1
    assert kb._safe_span("2.0") == 1
    assert kb._safe_span(None) == 1
    assert kb._safe_span(0) == 1
    assert kb._safe_span(-3) == 1
    assert kb._safe_span("3") == 3
    assert kb._safe_span(2) == 2

def test_parse_table_html_non_numeric_span_does_not_raise():
    """P1: attribute span không phải số → parse sống sót, span=1 (cả bs4
    lẫn regex path đều về 1 với giá trị không chứa digit)."""
    html = '<table><tr><td rowspan="foo">x</td></tr></table>'
    (row,) = kb._parse_table_html(html)
    assert row[0]["rowspan"] == 1

def test_parse_table_regex_single_quoted_span():
    """P2-2: regex fallback khớp quote đơn lẫn kép."""
    rows = kb._parse_table_regex("<table><tr><td colspan='2'>x</td></tr></table>")
    assert rows[0][0]["colspan"] == 2

def test_parse_table_nested_table_flattens_current_behavior():
    """P2-3 ceiling: nested table KHÔNG có scope riêng — tr inner bị flatten
    lẫn outer row (regex path). bs4 path find_all("tr") cũng flatten. Pin để
    biết nâng cấp (scope outermost table) sẽ đổi output."""
    html = (
        "<table><tr><td>a</td><td>b<table><tr><td>n</td></tr></table></td></tr>"
        "<tr><td>c</td><td>d</td></tr></table>"
    )
    rows = kb._parse_table_html(html)
    assert [[c["text"] for c in r] for r in rows] == [["a", "b n"], ["c", "d"]]

def test_table_cells_to_md_gfm_pipe_header_separator():
    cells = kb._parse_table_html(FIXTURE_TABLE_HTML)
    assert kb._table_cells_to_md(cells) == "| a | b |\n| --- | --- |\n| c | d |"

def test_table_cells_to_md_colspan_repeats_rowspan_dropped():
    """colspan → lặp text ô; rowspan → bỏ (GFM pipe không có span — docx giữ)."""
    cells = [
        [{"text": "x", "rowspan": 2, "colspan": 2, "header": False}],
        [{"text": "y", "rowspan": 1, "colspan": 1, "header": False}],
    ]
    assert kb._table_cells_to_md(cells) == "| x | x |\n| --- | --- |\n| y |"

def test_table_cells_to_md_escapes_pipe():
    cells = [[{"text": "a|b", "rowspan": 1, "colspan": 1, "header": True}]]
    assert kb._table_cells_to_md(cells) == "| a\\|b |\n| --- |"

def test_extract_blocks_table_gains_cells_html_flat_text():
    """wave-3: block table → html (nguồn sự thật) + cells (parse 1 lần) +
    text phẳng (result.jsonb regions dùng)."""
    raw = {"res": {"parsing_res_list": [
        {"block_bbox": [0, 0, 10, 10], "block_content": FIXTURE_TABLE_HTML,
         "block_label": "table"},
        {"block_bbox": [0, 20, 10, 30], "block_content": "text thường",
         "block_label": "text"},
    ]}}
    blocks = kb.extract_blocks(raw, 1)
    t = blocks[0]
    assert t["html"] == FIXTURE_TABLE_HTML
    assert [[c["text"] for c in r] for r in t["cells"]] == [["a", "b"], ["c", "d"]]
    assert t["text"] == "a | b\nc | d"
    # text thường không table → giữ nguyên
    assert "cells" not in blocks[1] and blocks[1]["text"] == "text thường"

def test_extract_blocks_table_parse_fail_keeps_html_text():
    raw = {"res": {"parsing_res_list": [
        {"block_bbox": [0, 0, 10, 10], "block_content": "<table><div>hỏng",
         "block_label": "table"}]}}
    (b,) = kb.extract_blocks(raw, 1)
    assert "cells" not in b and b["text"] == "<table><div>hỏng"

def test_page_md_table_renders_pipe_not_html():
    blocks = kb.extract_blocks({"res": {"parsing_res_list": [
        {"block_bbox": [0, 0, 10, 10], "block_content": FIXTURE_TABLE_HTML,
         "block_label": "table"}]}}, 1)
    assert kb._page_md(blocks) == "| a | b |\n| --- | --- |\n| c | d |"

def test_page_md_two_columns_left_before_right():
    """b15/b17 shape (job1 đề Hóa): 2 vùng cùng hàng → trái trước."""
    blocks = [
        {"id": "p1_b17", "type": "text", "bbox": [345, 518, 583, 713],
         "text": "phải", "empty": False},
        {"id": "p1_b15", "type": "text", "bbox": [60, 602, 322, 713],
         "text": "trái", "empty": False},
    ]
    assert kb._page_md(blocks) == "trái\n\nphải"

def test_page_md_two_image_markers_same_row_one_line():
    blocks = [
        {"id": "b15", "type": "image", "bbox": [60, 602, 322, 713],
         "text": "", "empty": True},
        {"id": "b17", "type": "image", "bbox": [345, 518, 583, 713],
         "text": "", "empty": True},
    ]
    m15 = kb.IMAGE_MARKER.format(region_id="b15")
    m17 = kb.IMAGE_MARKER.format(region_id="b17")
    assert kb._page_md(blocks) == f"{m15} {m17}"  # cùng hàng → 1 dòng, trái trước

def test_page_md_image_marker_lone_own_line():
    blocks = [
        {"id": "b0", "type": "image", "bbox": [60, 100, 322, 200],
         "text": "", "empty": True},
        {"id": "b1", "type": "image", "bbox": [60, 600, 322, 700],
         "text": "", "empty": True},
    ]
    md = kb._page_md(blocks)
    assert md == (kb.IMAGE_MARKER.format(region_id="b0") + "\n\n"
                  + kb.IMAGE_MARKER.format(region_id="b1"))

def test_page_md_plain_text_join_unchanged():
    blocks = [
        {"id": "b0", "type": "text", "bbox": [0, 0, 10, 10],
         "text": "a", "empty": False},
        {"id": "b1", "type": "text", "bbox": [0, 20, 10, 30],
         "text": "b", "empty": False},
    ]
    assert kb._page_md(blocks) == "a\n\nb"

def test_image_marker_parity_with_server_schemas():
    """kernel standalone không import được server — hằng phải khớp 1-1."""
    from app.core.schemas import IMAGE_MARKER
    assert kb.IMAGE_MARKER == IMAGE_MARKER

def test_rasterize_image_input_closes_handles(tmp_path, monkeypatch):
    """review r1 P2: Image.open đầu tiên trong rasterize (đọc size) phải
    được close — spy mọi handle mở ra."""
    from PIL import Image

    opened: list = []
    real_open = Image.open

    class _Spy:
        def __init__(self, fp, *a, **k):
            self._im = real_open(fp, *a, **k)
            self.closed = False
            opened.append(self)

        def __getattr__(self, name):
            return getattr(self._im, name)

        def __enter__(self):
            return self._im

        def __exit__(self, *exc):
            self._im.close()
            self.closed = True
            return False

    monkeypatch.setattr(Image, "open", lambda fp, *a, **k: _Spy(fp, *a, **k))
    src = tmp_path / "in.jpg"
    Image.new("RGB", (10, 6), "red").save(src, "JPEG")
    kb.rasterize_to_pages(str(src), str(tmp_path / "raw"))
    assert opened and all(s.closed for s in opened), "mọi Image.open phải đóng"
