"""Preview layout spec: result.json → preview.md + preview.docx (không DB/LLM).

    cd server && .venv/bin/python scripts/preview_layout.py <result.json> [outdir]
        [--crops-dir <dir>]

--crops-dir: nhúng ảnh crop `{dir}/{rid}.png|jpg` vào docx; thiếu → placeholder.
In tóm tắt: số trang, số cột mỗi trang, số block, số tab stop, số section.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document  # noqa: E402

from app.services.layout_spec import build_page_specs  # noqa: E402
from app.services.render_docx import build_docx, render_docx_spec  # noqa: E402
from app.services.render_md import build_md  # noqa: E402


def _crops_loader(crops_dir: Path):
    """async (rid) → bytes | None — đọc {crops_dir}/{rid}.png|jpg."""
    async def _load(rid: str) -> bytes | None:
        for ext in ("png", "jpg"):
            p = crops_dir / f"{rid}.{ext}"
            if p.exists():
                return p.read_bytes()
        return None
    return _load

def main(argv: list[str]) -> int:
    crops_dir: Path | None = None
    positional: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--crops-dir" and i + 1 < len(argv):
            crops_dir = Path(argv[i + 1])
            i += 2
            continue
        positional.append(argv[i])
        i += 1
    if len(positional) < 2:
        print(__doc__)
        return 2
    src = Path(positional[1])
    outdir = Path(positional[2]) if len(positional) > 2 else src.parent
    outdir.mkdir(parents=True, exist_ok=True)
    result = json.loads(src.read_text(encoding="utf-8"))

    md = asyncio.run(build_md(result, use_llm=False))
    if crops_dir is None:
        docx_bytes = render_docx_spec(result)
    else:
        docx_bytes = asyncio.run(
            build_docx(result, crop_loader=_crops_loader(crops_dir))
        )
    if not md.endswith("\n"):
        md += "\n"
    (outdir / "preview.md").write_text(md, encoding="utf-8")
    (outdir / "preview.docx").write_bytes(docx_bytes)

    pages = build_page_specs(result)
    doc = Document(io.BytesIO(docx_bytes))
    n_blocks = sum(len(pg.blocks) for pg in pages)
    n_tabs = sum(len(b.tabs) for pg in pages for b in pg.blocks)
    print(f"file      : {src}")
    print(f"outdir    : {outdir}")
    if crops_dir is not None:
        print(f"crops-dir : {crops_dir}")
    print(f"pages     : {len(pages)}")
    print("cols/page : " + ", ".join(str(len(pg.cols)) for pg in pages))
    for i, pg in enumerate(pages):
        per: dict[int, int] = {}
        for b in pg.blocks:
            per[b.col_index] = per.get(b.col_index, 0) + 1
        counts = " ".join(f"blocks[c{c}]={n}" for c, n in sorted(per.items()))
        print(f"p{i} {src.stem}: cols={len(pg.cols)} {counts}")
    print(f"blocks    : {n_blocks}")
    print(f"tab stops : {n_tabs}")
    print(f"sections  : {len(doc.sections)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
