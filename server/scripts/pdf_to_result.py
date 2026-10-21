"""PDF scan → result.json (shape spec §4) bằng tesseract, không LLM/DB.

    cd server && .venv/bin/python scripts/pdf_to_result.py <file.pdf> \
        [--out /tmp/x_result.json] [--zoom 1.0] [--lang vie+eng] [--jobs 4]

PDF không có text layer (scan) → pymupdf render từng trang PNG (zoom 1.0 =
đúng px trang, ~258 dpi với A4 scan 2133×3017) → `tesseract ... tsv`. Word
TSV gom theo (block_num, par_num) → 1 region `p{page}_b{i}`: bbox = union
word bbox, text = words ghép theo line/word, verdict="ok". Page `markdown` =
text các block nối theo thứ tự đọc (để variant A khác B thật).

tessdata project-local: `.tools/tessdata` (xem README/step tải vie.traineddata).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf

REPO = Path(__file__).resolve().parents[2]
TESSDATA = REPO / ".tools" / "tessdata"
TSV_COLS = 11

def _ocr(png: Path, lang: str) -> str:
    cmd = [
        "tesseract", str(png), "stdout",
        "--tessdata-dir", str(TESSDATA), "-l", lang, "--psm", "3", "tsv",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract fail ({proc.returncode}): {proc.stderr[:300]}")
    return proc.stdout

def _regions(tsv: str, page_index: int) -> list[dict]:
    """Word TSV → region theo (block_num, par_num)."""
    blocks: dict[tuple[int, int], list[tuple[int, int, list[str], list[float]]]] = {}
    for line in tsv.splitlines()[1:]:          # bỏ header
        cols = line.split("\t")
        if len(cols) < TSV_COLS or cols[0] != "5":   # level 5 = word
            continue
        word = cols[TSV_COLS - 1].strip()
        if not word:
            continue
        left, top, width, height = (int(cols[i]) for i in (6, 7, 8, 9))
        key = (int(cols[2]), int(cols[3]))     # block_num, par_num
        blocks.setdefault(key, []).append(
            (int(cols[4]), int(cols[5]), word, [left, top, left + width, top + height])
        )

    out: list[dict] = []
    for words in sorted(blocks.values(), key=lambda ws: (min(w[3][1] for w in ws), min(w[3][0] for w in ws))):
        words.sort(key=lambda w: (w[0], w[1]))
        lines: dict[int, list[str]] = {}
        for line_num, _, word, _ in words:
            lines.setdefault(line_num, []).append(word)
        bbox = [
            min(w[3][0] for w in words), min(w[3][1] for w in words),
            max(w[3][2] for w in words), max(w[3][3] for w in words),
        ]
        out.append({
            "id": f"p{page_index}_b{len(out)}",
            "bbox": bbox,
            "text": "\n".join(" ".join(ws) for _, ws in sorted(lines.items())),
            "verdict": "ok",
        })
    return out

def _render(pdf: pymupdf.Document, index: int, zoom: float, tmp: Path) -> tuple[Path, int, int]:
    """pymupdf KHÔNG thread-safe: render tuần tự ở main thread, chỉ OCR song song."""
    pix = pdf[index].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    png = tmp / f"p{index}.png"
    pix.save(png)
    return png, pix.width, pix.height

def _ocr_page(png: Path, index: int, lang: str, width: int, height: int) -> dict:
    regions = _regions(_ocr(png, lang), index)
    return {
        "index": index,
        "width": width,
        "height": height,
        "page_flag": "ok",
        "regions": regions,
        "markdown": "\n\n".join(r["text"] for r in regions),
    }

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--zoom", type=float, default=1.0,
                    help="1.0 = đúng px trang (A4 scan 2133×3017 ≈ 258 dpi)")
    ap.add_argument("--lang", default="vie+eng")
    ap.add_argument("--jobs", type=int, default=1,
                    help="số trang OCR song song — tesseract ~1GB/trang, 4 job = OOM/hang trên máy 7GB")
    ap.add_argument("--pages", type=int, default=999, help="chỉ OCR N trang đầu")
    args = ap.parse_args(argv)

    if not TESSDATA.exists():
        print(f"thiếu {TESSDATA} — tải traineddata trước (xem docstring)", file=sys.stderr)
        return 2
    langs = {p.stem for p in TESSDATA.glob("*.traineddata")}
    missing = [l for l in re.split(r"\+", args.lang) if l not in langs]
    if missing:
        print(f"thiếu traineddata: {missing} trong {TESSDATA}", file=sys.stderr)
        return 2

    out = args.out or Path("/tmp") / f"{args.pdf.stem}_result.json"
    pdf = pymupdf.open(args.pdf)
    limit = min(pdf.page_count, args.pages)  # --pages: bench trên N trang đầu
    with tempfile.TemporaryDirectory(prefix="pdf2result_") as tmpdir:
        tmp = Path(tmpdir)
        rendered = [_render(pdf, i, args.zoom, tmp) for i in range(limit)]
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            pages = list(pool.map(
                lambda item: _ocr_page(item[0], item[1][0], args.lang, item[1][1], item[1][2]),
                [(r[0], (i, r[1], r[2])) for i, r in enumerate(rendered)],
            ))
    result = {
        "model_version": f"tesseract-tsv/{args.lang}",
        "gpu_seconds": 0.0,
        "warnings": [],
        "pages": pages,
    }
    out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    counts = [len(p["regions"]) for p in pages]
    print(f"pdf   : {args.pdf} ({limit}/{pdf.page_count} trang)")
    print(f"out   : {out} ({out.stat().st_size / 1024:.0f} KB)")
    print(f"size  : {pages[0]['width']}×{pages[0]['height']} px  zoom={args.zoom}")
    print(f"region: {sum(counts)} tổng, {min(counts)}–{max(counts)}/trang "
          f"(TB {sum(counts) / len(counts):.1f})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
