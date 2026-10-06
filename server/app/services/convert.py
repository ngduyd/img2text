"""Pandoc invocation constants (Plan D Task 3, ruling R25: no-sudo install).

PANDOC_BIN: static binary under server/.tools/ (gitignored), env override;
REFERENCE_DOCX: committed styles at deploy/reference.docx for docx exports.
"""

import os
from pathlib import Path

# R25: static pandoc binary in server/.tools/ (gitignored); env override.
PANDOC_BIN = os.environ.get(
    "PANDOC_BIN", str(Path(__file__).parents[2] / ".tools" / "pandoc" / "pandoc")
)
# Committed reference styles at repo root deploy/reference.docx.
REFERENCE_DOCX = str(Path(__file__).parents[3] / "deploy" / "reference.docx")
