"""Phase 1 Task 3: incremental layout sync (text replace, 0 LLM)."""

from app.services.layout_sync import sync_docx_html, sync_job_layouts, sync_md_layout


def test_md_replace_all():
    assert sync_md_layout("xin chào thế giới, chào bạn", "chào", "hello", 1) == \
        "xin hello thế giới, chào bạn"


def test_md_replace_not_found():
    assert sync_md_layout("abc", "xyz", "y", -1) is None


def test_docx_replace_in_span_keeps_tags():
    html = '<div><p>viết <span class="x">sai</span> chính tả</p></div>'
    out = sync_docx_html(html, "sai", "xài")
    assert out == '<div><p>viết <span class="x">xài</span> chính tả</p></div>'


def test_docx_replace_nested_tags():
    html = "<p>a <em>b <strong>c</strong> b</em> a</p>"
    out = sync_docx_html(html, "b", "X")
    assert out == "<p>a <em>X <strong>c</strong> X</em> a</p>"


def test_docx_not_in_attributes():
    # phrase only inside an attribute → not a text node → not found
    assert sync_docx_html('<img src="sai.jpg" alt="sai">', "sai", "xài") is None


def test_docx_spans_two_text_nodes_not_found():
    assert sync_docx_html("<p>sai <em>lỗi</em></p>", "sai lỗi", "x") is None


async def test_sync_job_layouts(storage):
    await storage.put("exports/9/md-layout", b"noi dung sai")
    await storage.put(
        "exports/9/docx.html", "<p>doc sai</p>".encode("utf-8")
    )
    out = await sync_job_layouts(storage, 9, "sai", "xài")
    assert out == {"md": True, "docx": True}
    assert await storage.get("exports/9/md-layout") == "noi dung xài".encode("utf-8")
    assert await storage.get("exports/9/docx.html") == b"<p>doc x\xc3\xa0i</p>"


async def test_sync_job_layouts_not_found(storage):
    out = await sync_job_layouts(storage, 9, "khongco", "x")
    assert out == {"md": False, "docx": False}

def test_docx_replace_escapes_new():
    """P1-2: escaped new text — user content cannot inject markup into DOM."""
    assert sync_docx_html("<p>sai</p>", "sai", "a<b>c") == \
        "<p>a&lt;b&gt;c</p>"

async def test_sync_job_layouts_failure_isolated(storage):
    """P2: one layout failing (storage error) → other still syncs, no abort."""
    await storage.put("exports/9/md-layout", b"noi dung sai")
    await storage.put("exports/9/docx.html", b"<p>doc sai</p>")
    real_get = storage.get

    async def flaky_get(key):
        if key == "exports/9/md-layout":
            raise RuntimeError("s3 down")
        return await real_get(key)

    storage.get = flaky_get
    out = await sync_job_layouts(storage, 9, "sai", "x")
    assert out == {"md": False, "docx": True}
    assert await storage.get("exports/9/docx.html") == b"<p>doc x</p>"
