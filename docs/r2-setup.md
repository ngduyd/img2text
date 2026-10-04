# R2 — bucket setup

Plan G docs task 3 owns the full R2 bucket setup content.

## Rebuild deploy/reference.docx

`deploy/reference.docx` is a committed artifact used as pandoc's
`--reference-doc` for DOCX export. After any change to
`deploy/make_reference_docx.py`, rebuild and commit the artifact:

```bash
python deploy/make_reference_docx.py deploy/reference.docx
```

`server/tests/test_reference_rebuild.py` fails if the committed artifact
drifts from the builder's output.
