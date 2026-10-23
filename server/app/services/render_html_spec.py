"""OCR result → HTML preview dựng từ layout_spec (nguồn sự thật duy nhất).

Vì sao cần: preview Word trên web trước đây convert docx bằng `mammoth` —
mammoth là content extractor, nó bỏ `w:tab` (tab stop), `w:jc` (canh lề) và
OMML (công thức). Kết quả: bản xem trước KHÁC bản tải về (mất công thức, mất
header 2 bên, mất justify). Renderer này dựng HTML trực tiếp từ spec:

- tab (dòng có "\\t")  → flex 2 đầu (giữ vị trí trái/phải)
- align                → CSS text-align (justify dùng được)
- latex                → MathML (latex2mathml) — browser render như công thức
- image                → crop route (ảnh thật, không phải placeholder)
- table                → <table> có rowspan/colspan

Không phải bản dựng lại 100% Word (không tab-stop tuỳ ý, không cột thật) —
ceiling: đủ để người dùng thấy đúng công thức / 2 bên / canh đều. Nâng lên
soffice-headless render docx→PNG khi cần pixel-perfect.
"""

from __future__ import annotations

import html as _html

from app.services.layout_spec import BlockSpec, PageSpec, build_page_specs

CSS = """<style>
/* docStyle của app (prose 65ch) bóp trang còn ~580px → cột 24% chỉ còn
   130px, chữ gãy dòng. Preview layout phải dùng HẾT bề ngang iframe. */
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
     font-size:15px;line-height:1.5;color:#111;margin:0;padding:12px;
     max-width:none;width:auto}
.pg{margin:0 auto 24px;overflow-wrap:break-word}
/* cột đặt theo VỊ TRÍ thật trên trang: grid 100 track = 1% bề ngang trang */
.cols{display:grid;grid-template-columns:repeat(100,minmax(0,1fr))}
.col{min-width:0}
.pg+.pg{border-top:1px dashed #ccc;padding-top:12px}
.row{display:flex;align-items:baseline;gap:1em;margin:0 0 .5em}
.row>.l{flex:0 0 auto;white-space:nowrap}
.row .r{margin-left:auto;text-align:right;white-space:pre-wrap}
p{margin:0 0 .5em}
.math{text-align:center;margin:.7em 0;overflow-x:auto}
.h1{font-size:1.4em;font-weight:700;margin:.8em 0 .4em}
.h2{font-size:1.2em;font-weight:700;margin:.7em 0 .35em}
table{border-collapse:collapse;width:100%;margin:.6em 0}
td,th{border:1px solid #999;padding:4px 6px;vertical-align:top;text-align:left}
.lead{border-bottom:1px dotted #666;flex:1 1 auto;min-width:2em}
img{max-width:100%;height:auto;display:block}
.ph{color:#888;font-style:italic}
</style>"""


def _mathml(latex: str) -> str | None:
    try:
        from latex2mathml.converter import convert
    except ImportError:  # pragma: no cover - main dep
        return None
    try:
        return convert(latex)
    except Exception:  # latex lạ → fallback text
        return None


def _esc(text: str) -> str:
    return _html.escape(text, quote=False)


def _table_html(blk: BlockSpec) -> str:
    if not blk.cells:
        return f'<p class="ph">{_esc(blk.text)[:200]}</p>'
    rows: list[str] = []
    for row in blk.cells:
        cells: list[str] = []
        for cell in row:
            rs = max(1, int(cell.get("rowspan") or 1))
            cs = max(1, int(cell.get("colspan") or 1))
            tag = "th" if cell.get("header") else "td"
            span = (f' rowspan="{rs}"' if rs > 1 else "") + (
                f' colspan="{cs}"' if cs > 1 else ""
            )
            cells.append(f"<{tag}{span}>{_esc(str(cell.get('text') or ''))}</{tag}>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def _line_html(line: str, style: str, tab_pos_px: float | None = None,
               tab_align: str = "left", col_w: float | None = None) -> str:
    """1 dòng: có tab → 2 đầu (trái/phải); không tab → <p>.

    Dòng bắt đầu bằng tab (dòng nối của khối bị gộp tab) phải canh theo ĐÚNG
    tab stop: mép phải của text = tab pos (right tab) — không phải mép phải
    trang như flex space-between.
    """
    if "\t" not in line:
        return f'<p style="{style}">{_esc(line)}</p>'
    if line.startswith("\t") and tab_pos_px is not None and col_w:
        pct = max(0.0, min(100.0, 100.0 * tab_pos_px / col_w))
        # KHÔNG dùng lại style của block (margind-left + text-align:left sẽ
        # cộng dồn → tràn dòng); dòng tab có hệ toạ độ riêng.
        if tab_align == "right":
            st = f"width:{pct:.1f}%;text-align:right;margin:0 0 .3em 0"
        else:
            st = (
                f"margin:0 0 .3em {pct:.1f}%;"
                f"width:{max(0.0, 100.0 - pct):.1f}%;text-align:left"
            )
        return f'<p style="{st}">{_esc(line[1:])}</p>'
    left, _, right = line.partition("\t")
    if right.strip() and (left.rstrip().endswith(".") or "...." in left):
        # nhãn form: "Địa chỉ: ........." + giá trị → giữ kiểu leader chấm
        return (
            f'<div class="row" style="{style}"><span class="l">{_esc(left)}</span>'
            f'<span class="lead"></span><span class="r">{_esc(right)}</span></div>'
        )
    return (
        f'<div class="row" style="{style}"><span class="l">{_esc(left)}</span>'
        f'<span class="r">{_esc(right)}</span></div>'
    )


def _image_box(blk: BlockSpec, pg: PageSpec) -> str:
    """Ảnh giữ đúng bề ngang + vị trí tương đối trong cột (figure bên phải
    không được kéo full-width như bản preview cũ)."""
    col = pg.cols[min(blk.col_index, len(pg.cols) - 1)]
    col_w = max(1.0, col.x1 - col.x0)
    width = min(100.0, 100.0 * max(1.0, blk.x1 - blk.x0) / col_w)
    left = max(0.0, min(100.0 - width, 100.0 * (blk.x0 - col.x0) / col_w))
    return f'width:{width:.1f}%;margin-left:{left:.1f}%'


def _block_html(blk: BlockSpec, crop_url: str | None,
                pg: PageSpec | None = None) -> str:
    if blk.kind == "image":
        if crop_url:
            box = _image_box(blk, pg) if pg is not None else ""
            return f'<img src="{crop_url}" style="{box}" alt="">'
        return f'<p class="ph">[ảnh {_esc(blk.region_id)}]</p>'
    if blk.kind == "table":
        return _table_html(blk)
    if blk.latex:
        mathml = _mathml(blk.latex)
        if mathml:
            return f'<div class="math">{mathml}</div>'
    styles = [f"text-align:{blk.align}"]
    # giống render_docx: indent chỉ áp cho canh trái (canh phải/giữa mà cộng
    # margin-left sẽ đẩy chữ ra ngoài trang — footer "Trang 1/5" từng mất)
    if blk.align == "left" and blk.indent_px > 0.5:
        styles.append(f"margin-left:{round(blk.indent_px)}px")
    if blk.first_line_indent_px > 0.5:
        styles.append(f"text-indent:{round(blk.first_line_indent_px)}px")
    style = ";".join(styles)
    lines = blk.lines or ([blk.text] if blk.text else [])
    col_w = None
    if pg is not None and len(pg.cols) > blk.col_index:
        col = pg.cols[blk.col_index]
        col_w = max(1.0, col.x1 - col.x0)
    tab = blk.tabs[0] if blk.tabs else None

    def line_html(ln: str) -> str:
        return _line_html(
            ln, style,
            tab_pos_px=tab.pos_px if tab else None,
            tab_align=tab.align if tab else "left",
            col_w=col_w,
        )

    if blk.type_label == "heading" and blk.level:
        inner = "".join(line_html(ln) for ln in lines)
        return f'<div class="h{min(2, blk.level)}" style="{style}">{inner}</div>'
    return "".join(line_html(line) for line in lines)


def _page_body(pg: PageSpec, crop_urls: dict[str, str] | None) -> str:
    """Blocks của 1 trang; nhiều cột → flex 2+ cột đúng tỉ lệ bề ngang gốc.

    Trước: render phẳng theo thứ tự block → trang 2 cột hiện thành 1 cột (bản
    xem trước sai, dù docx đã có <w:cols num="2">).
    """
    def one(blk: BlockSpec) -> str:
        crop_url = (crop_urls or {}).get(blk.region_id)
        return _block_html(blk, crop_url, pg)

    if len(pg.cols) <= 1:
        return "".join(one(b) for b in pg.blocks)

    # đặt cột theo x0/x1 thật của trang (grid 100 track = 1% bề ngang) —
    # flex trước đây dồn 2 cột sát nhau, lệch vị trí so với bản gốc
    span = max(1.0, pg.width or (pg.cols[-1].x1 - pg.cols[0].x0))
    by_col: dict[int, list[BlockSpec]] = {}
    for blk in pg.blocks:
        by_col.setdefault(blk.col_index, []).append(blk)
    parts = ['<div class="cols">']
    for ci, col in enumerate(pg.cols):
        start = round(100.0 * max(0.0, col.x0) / span)
        width = max(1, round(100.0 * max(1.0, col.x1 - col.x0) / span))
        width = min(width, 100 - min(start, 99))
        parts.append(
            f'<div class="col" style="grid-column:{start + 1} / span {width}">'
            + "".join(one(b) for b in by_col.get(ci, []))
            + "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def render_html_spec(
    result: dict,
    crop_prefix: str | None = None,
    crop_urls: dict[str, str] | None = None,
) -> str:
    """result §4 → HTML preview.

    crop_urls: {region_id: url} (ưu tiên — presigned crop thật);
    crop_prefix: fallback "/api/jobs/37/regions/" → "{prefix}{rid}/crop".
    """
    page_specs: list[PageSpec] = build_page_specs(result)
    parts = [CSS]
    for pi, pg in enumerate(page_specs):
        urls = dict(crop_urls or {})
        if crop_prefix:
            for blk in pg.blocks:
                urls.setdefault(blk.region_id, f"{crop_prefix}{blk.region_id}/crop")
        # giữ đúng bề ngang trang gốc: nếu kéo full iframe thì xuống dòng
        # khác bản gốc (trang 640 px mà khung 1150 px → 2 dòng thành 1)
        page_px = round(min(pg.width, 2000.0)) if pg.width else 0
        style = f' style="max-width:{page_px}px"' if page_px else ""
        parts.append(f'<div class="pg" data-page="{pi}"{style}>')
        parts.append(_page_body(pg, urls))
        parts.append("</div>")
    return "".join(parts)
