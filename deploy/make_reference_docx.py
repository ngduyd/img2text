"""Build deploy/reference.docx — pandoc reference styles (Plan D Task 3).

Run once: `.venv/bin/python deploy/make_reference_docx.py` → writes
deploy/reference.docx (committed artifact; exports use --reference-doc).
"""

from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.shared import Pt


def make_reference_docx(path: str) -> None:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12)):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = True
    if "Table Grid" not in {s.name for s in doc.styles}:
        doc.styles.add_style("Table Grid", WD_STYLE_TYPE.TABLE)
    doc.save(path)


if __name__ == "__main__":
    out = Path(__file__).parent / "reference.docx"
    make_reference_docx(str(out))
    print(out)
