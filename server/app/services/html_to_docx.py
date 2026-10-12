"""Plan M3: docx.html (user-edited word HTML) → docx bytes, python-docx walker.

Subset emitted: p/div, h1-h3, b/i/u, span[style font-size/font-family],
ul/ol/li, table/tr/th/td, align attrs — font/size/align/table/underline
preserved (pandoc loses inline styles → own walker). ponytail: img/other
tags dropped, nested tables flatten — upgrade path: images + colspan if
the web word mode starts emitting them.
"""

import io
import logging
import re
from html.parser import HTMLParser

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

logger = logging.getLogger(__name__)

_ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_HEADINGS = {"h1": "Heading 1", "h2": "Heading 2", "h3": "Heading 3"}
_LISTS = {"ul": "List Bullet", "ol": "List Number"}
_BLOCKS = {"p", "div", "h1", "h2", "h3", "li"}
_SKIP_CONTENT = {"script", "style", "head", "title", "meta", "link"}
# font-size: "14pt" | "18.5px" | "14" (execCommand styleWithCSS variants)
_SIZE_RE = re.compile(r"([\d.]+)\s*(pt|px)?")
# crop ref: src chứa "crops/{rid}.png" (relative HOẶC presigned URL đầy đủ)
CROP_SRC_RE = re.compile(r"crops/([^/?#]+)\.[a-z]+", re.IGNORECASE)


class _Node:
    __slots__ = ("tag", "attrs", "kids")

    def __init__(self, tag: str, attrs: dict, kids: list):
        self.tag = tag
        self.attrs = attrs
        self.kids = kids  # str | _Node


class _TreeParser(HTMLParser):
    """Tolerant HTML → _Node tree; script/style CONTENT dropped (XSS inert)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, [])
        self.stack = [self.root]
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._skip:
            if tag in _SKIP_CONTENT:
                self._skip += 1
            return
        node = _Node(tag, dict(attrs), [])
        self.stack[-1].kids.append(node)
        if tag in _SKIP_CONTENT:
            self._skip = 1
            self.stack.append(node)
        elif tag not in ("br", "img", "hr", "input", "meta", "link"):
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag in _SKIP_CONTENT:
                self._skip -= 1
                if len(self.stack) > 1 and self.stack[-1].tag == tag:
                    self.stack.pop()
            return
        # tolerant close: pop back to matching open tag (HTML often omits </p>)
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self.stack[-1].kids.append(data)


def _style_of(node: "_Node") -> dict:
    """span/element style → {font, size_pt, underline} from CSS decls."""
    out: dict = {}
    decls = node.attrs.get("style", "")
    for decl in decls.split(";"):
        name, _, val = decl.partition(":")
        name = name.strip().lower()
        val = val.strip()
        if name == "font-family":
            out["font"] = val.split(",")[0].strip("'\"") or None
        elif name == "font-size":
            m = _SIZE_RE.match(val)
            if m:
                num = float(m.group(1))
                # px → pt (96dpi CSS); bare number already pt (execCommand)
                out["size_pt"] = num * 0.75 if m.group(2) == "px" else num
        elif name == "text-decoration" and "underline" in val:
            out["underline"] = True
    return out


class _Walker:
    """Tree → python-docx. Inline style stack + lazy current paragraph."""

    def __init__(self, crops: dict[str, bytes] | None = None) -> None:
        self.doc = Document()
        self.crops = crops or {}
        self.para = None  # open paragraph (None → created lazily on text)
        self.container = self.doc  # current target (doc | table cell)
        self.pending: dict = {}  # paragraph props for the NEXT created para
        self.inline: dict = {}  # inherited run style stack frame copy

    def _close_para(self) -> None:
        self.para = None

    def _ensure(self):
        if self.para is None:
            self.para = self.container.add_paragraph()
            style = self.pending.get("list")
            if style:
                try:
                    self.para.style = self.doc.styles[style]
                except KeyError:  # ponytail: missing list style → plain para
                    pass
            align = self.pending.get("align")
            if align is not None:
                self.para.alignment = align
        return self.para

    def _run(self, text: str) -> None:
        run = self._ensure().add_run(text)
        st = self.inline
        if st.get("bold"):
            run.bold = True
        if st.get("italic"):
            run.italic = True
        if st.get("underline"):
            run.underline = True
        if st.get("font"):
            run.font.name = st["font"]
        if st.get("size_pt"):
            run.font.size = Pt(st["size_pt"])

    def walk(self, nodes: list) -> None:
        for node in nodes:
            if isinstance(node, str):
                text = re.sub(r"\s+", " ", node)
                if text:
                    self._run(text)
                continue
            tag = node.tag
            if tag in _SKIP_CONTENT:
                continue
            if tag in ("b", "strong"):
                self._push({"bold": True}, node)
            elif tag in ("i", "em"):
                self._push({"italic": True}, node)
            elif tag == "u":
                self._push({"underline": True}, node)
            elif tag == "span":
                self._push(_style_of(node), node)
            elif tag == "br":
                self._ensure().add_run().add_break()
            elif tag == "img":
                self._image(node)
            elif tag in _BLOCKS or tag == "div":
                self._block(node, tag)
            elif tag in _LISTS:
                self._close_para()
                for kid in node.kids:
                    if isinstance(kid, _Node) and kid.tag == "li":
                        self._list_item(kid, _LISTS[tag])
            elif tag == "table":
                self._table(node)
            else:  # unknown/unsupported tag: unwrap, keep children
                self.walk(node.kids)

    def _image(self, node: "_Node") -> None:
        """WS-PIPE: img src → crop bytes embed trực tiếp (không phụ thuộc URL
        presigned — hết hạn cũng không hỏng export). Crop thiếu → drop (cũ)."""
        m = CROP_SRC_RE.search(node.attrs.get("src", ""))
        data = self.crops.get(m.group(1)) if m else None
        if data:
            try:
                self._ensure().add_run().add_picture(io.BytesIO(data))
            except Exception as exc:  # bytes hỏng → drop img như crop thiếu
                logger.warning("docx: crop bytes hỏng, bỏ img: %s", exc)

    def _push(self, extra: dict, node: "_Node") -> None:
        """Inline element: recurse with merged style, restore after."""
        saved = self.inline
        self.inline = {**saved, **extra}
        self.walk(node.kids)
        self.inline = saved

    def _para_ctx(self, node: "_Node", tag: str, list_style: str | None) -> None:
        self._close_para()  # new block → new paragraph (empty → not created)
        pending: dict = {}
        if list_style:
            pending["list"] = list_style
        elif tag in _HEADINGS:
            pending["list"] = None
            pending["heading"] = _HEADINGS[tag]
        align = node.attrs.get("align", "").lower()
        if not align:
            align = re.search(
                r"text-align\s*:\s*(\w+)", node.attrs.get("style", ""), re.I
            )
            align = align.group(1).lower() if align else ""
        if align in _ALIGN:
            pending["align"] = _ALIGN[align]
        self.pending = pending
        # span font/size on the block itself applies to its runs
        block_style = _style_of(node)
        if block_style:
            saved = self.inline
            self.inline = {**saved, **block_style}
            self._walk_then(node, saved)
        else:
            self._walk_then(node, self.inline)

    def _walk_then(self, node: "_Node", restore: dict) -> None:
        heading = self.pending.get("heading")
        if heading:
            # heading needs eager paragraph (style before first run)
            self.para = self.container.add_paragraph(style=heading)
            if self.pending.get("align") is not None:
                self.para.alignment = self.pending["align"]
            saved_pending = self.pending
            self.pending = {}
            self.walk(node.kids)
            self.pending = saved_pending
        else:
            self.walk(node.kids)
        self.inline = restore
        self._close_para()

    def _block(self, node: "_Node", tag: str) -> None:
        self._para_ctx(node, tag, None)

    def _list_item(self, node: "_Node", list_style: str) -> None:
        self._para_ctx(node, "li", list_style)

    def _table(self, node: "_Node") -> None:
        self._close_para()
        rows = [
            r for r in _rows(node)
        ]
        if not rows:
            self.walk(node.kids)
            return
        cols = max(len(_cells(r)) for r in rows)
        table = self.container.add_table(rows=len(rows), cols=cols)
        saved_container, saved_pending, saved_para = (
            self.container, self.pending, self.para
        )
        for ri, tr in enumerate(rows):
            for ci, td in enumerate(_cells(tr)):
                if ci >= cols:
                    break
                cell = table.rows[ri].cells[ci]
                self.container = cell
                self.para = cell.paragraphs[0]  # reuse default empty para
                self.pending = {}
                if td.tag == "th":
                    saved_inline = self.inline
                    self.inline = {**self.inline, "bold": True}
                    self.walk(td.kids)
                    self.inline = saved_inline
                else:
                    self.walk(td.kids)
                # cell paragraph alignment (align attr on td)
                align = td.attrs.get("align", "").lower()
                if align in _ALIGN and self.para is not None:
                    self.para.alignment = _ALIGN[align]
                self.para = None
        self.container, self.pending, self.para = (
            saved_container, saved_pending, saved_para
        )

    def render(self) -> bytes:
        buf = io.BytesIO()
        self.doc.save(buf)
        return buf.getvalue()


def _rows(table_node: "_Node") -> list:
    out = []
    for kid in table_node.kids:
        if isinstance(kid, _Node) and kid.tag == "tr":
            out.append(kid)
        elif isinstance(kid, _Node) and kid.tag in ("thead", "tbody", "tfoot"):
            out.extend(r for r in _rows(kid) if isinstance(r, _Node))
    return out


def _cells(tr: "_Node") -> list:
    return [
        k for k in tr.kids
        if isinstance(k, _Node) and k.tag in ("td", "th")
    ]


def html_to_docx(html: str, crops: dict[str, bytes] | None = None) -> bytes:
    """docx.html bytes-source → rendered .docx bytes (M3 export path).

    crops: {rid: png_bytes} — img src trỏ crop artifact (WS-PIPE) → embed
    bytes; None/không khớp → img drop như trước."""
    parser = _TreeParser()
    parser.feed(html)
    parser.close()
    walker = _Walker(crops)
    walker.walk(parser.root.kids)
    return walker.render()
