"""Plan D Task 3: reference.docx builder (brief test verbatim)."""

import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).parents[2] / "deploy"))
from make_reference_docx import make_reference_docx  # noqa: E402


def test_reference_docx_has_styles(tmp_path):
    p = tmp_path / "ref.docx"
    make_reference_docx(str(p))
    doc = Document(str(p))
    names = {s.name for s in doc.styles}
    assert {"Normal", "Heading 1", "Heading 2", "Heading 3", "Table Grid"} <= names
