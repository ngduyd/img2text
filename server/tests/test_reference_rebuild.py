"""Task 2 (Plan G): committed deploy/reference.docx must not drift from builder.

Guards the committed artifact: rebuilds a fresh reference.docx with
deploy/make_reference_docx.py and asserts the style sets match.

Import note: repo_root is inserted into sys.path so `deploy.make_reference_docx`
resolves (deploy/ has no __init__.py — implicit namespace package).
"""

import sys
from pathlib import Path

from docx import Document

repo_root = Path(__file__).parents[2]
sys.path.insert(0, str(repo_root))

from deploy.make_reference_docx import make_reference_docx  # noqa: E402


def test_committed_reference_matches_builder(tmp_path):
    fresh = tmp_path / "ref.docx"
    make_reference_docx(str(fresh))
    committed = repo_root / "deploy" / "reference.docx"
    assert committed.exists()
    a = Document(str(fresh))
    b = Document(str(committed))
    assert {s.name for s in a.styles} == {s.name for s in b.styles}
