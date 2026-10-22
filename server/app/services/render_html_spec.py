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
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
     font-size:15px;line-height:1.5;color:#111;margin:0;padding:12px}
.pg{margin:0 auto 24px;max-width:100%;overflow-wrap:break-word}
.pg+.pg{border-top:1px dashed #ccc;padding-top:12px}
.row{display:flex;align-items:baseline;gap:1em;margin:0 0 .5em}
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


def _line_html(line: str, style: str) -> str:
    """1 dòng: có tab → 2 đầu (trái/phải); không tab → <p>."""
    if "\t" not in line:
        return f'<p style="{style}">{_esc(line)}</p>'
    left, _, right = line.partition("\t")
    if right.strip() and (left.rstrip().endswith(".") or "...." in left):
        # nhãn form: "Địa chỉ: ........." + giá trị → giữ kiểu leader chấm
        return (
            f'<div class="row" style="{style}"><span>{_esc(left)}</span>'
            f'<span class="lead"></span><span class="r">{_esc(right)}</span></div>'
        )
    return (
        f'<div class="row" style="{style}"><span>{_esc(left)}</span>'
        f'<span class="r">{_esc(right)}</span></div>'
    )


def _block_html(blk: BlockSpec, crop_url: str | None) -> str:
    if blk.kind == "image":
        if crop_url:
            return f'<img src="{crop_url}" alt="">'
        return f'<p class="ph">[ảnh {_esc(blk.region_id)}]</p>'
    if blk.kind == "table":
        return _table_html(blk)
    if blk.latex:
        mathml = _mathml(blk.latex)
        if mathml:
            return f'<div class="math">{mathml}</div>'
    styles = [f"text-align:{blk.align}"]
    if blk.indent_px > 0.5:
        styles.append(f"margin-left:{round(blk.indent_px)}px")
    if blk.first_line_indent_px > 0.5:
        styles.append(f"text-indent:{round(blk.first_line_indent_px)}px")
    style = ";".join(styles)
    lines = blk.lines or ([blk.text] if blk.text else [])
    if blk.type_label == "heading" and blk.level:
        inner = "".join(_line_html(ln, style) for ln in lines)
        return f'<div class="h{min(2, blk.level)}" style="{style}">{inner}</div>'
    return "".join(_line_html(line, style) for line in lines)


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
        parts.append(f'<div class="pg" data-page="{pi}">')
        for blk in pg.blocks:
            crop_url = (crop_urls or {}).get(blk.region_id)
            if crop_url is None and crop_prefix:
                crop_url = f"{crop_prefix}{blk.region_id}/crop"
            parts.append(_block_html(blk, crop_url))
        parts.append("</div>")
    return "".join(parts)
