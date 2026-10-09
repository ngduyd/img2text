"""Kernel unit tests (spec 2026-10-09 batch one-run): find_inputs parses the
{job_id}__ staging prefix (sorted, dirs/unknown ext/non-prefixed skipped with
a log); run_batch continues past a failing job and sets the exit code from
outputs written. The module is imported DIRECTLY (import stays stdlib-only —
the pip/apt/venv bootstrap + heavy deps run only as __main__), no Kaggle."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "deploy" / "kaggle" / "kernel"))

import img2text_batch as kb  # noqa: E402


def test_find_inputs_parses_job_prefix_sorted_and_skips(tmp_path, capsys):
    (tmp_path / "5__b.png").write_bytes(b"x")
    (tmp_path / "3__a.pdf").write_bytes(b"x")
    (tmp_path / "10__c.jpg").write_bytes(b"x")
    sub = tmp_path / "owner" / "img2text-input"  # Kaggle nests mounts
    sub.mkdir(parents=True)
    (sub / "9__nested.png").write_bytes(b"x")
    (tmp_path / "noprefix.png").write_bytes(b"x")  # no {id}__ → skip + log
    (tmp_path / "abc__bad.png").write_bytes(b"x")  # non-numeric → skip
    (tmp_path / "dataset-metadata.json").write_text("{}")  # unknown ext → skip
    (tmp_path / "7__dir").mkdir()  # directory → skip
    got = kb.find_inputs(str(tmp_path))
    assert [job_id for job_id, _ in got] == [3, 5, 9, 10]  # NUMERIC sort
    assert all(Path(p).is_file() for _, p in got)
    assert "noprefix.png" in capsys.readouterr().out  # skip is logged


def test_find_inputs_empty_root_returns_empty(tmp_path):
    assert kb.find_inputs(str(tmp_path)) == []


def test_run_batch_continues_past_failing_job_and_exit_codes(monkeypatch):
    ok: list[int] = []

    def _ok(job_id, path):
        ok.append(job_id)

    def _boom(job_id, path):
        raise SystemExit("OCR phase exited 1 — xem log ở trên")

    def _only_job2_boom(job_id, path):
        if job_id == 2:
            _boom(job_id, path)
        ok.append(job_id)

    monkeypatch.setattr(kb, "process_job", _ok)
    # every job processed → exit 0
    assert kb.run_batch([(1, "a"), (2, "b"), (3, "c")]) == 0
    assert ok == [1, 2, 3]

    # job 2's error must NOT stop jobs 1/3 (continue-on-error) → still exit 0
    ok.clear()
    monkeypatch.setattr(kb, "process_job", _only_job2_boom)
    assert kb.run_batch([(1, "a"), (2, "b"), (3, "c")]) == 0
    assert ok == [1, 3]

    # zero outputs written → exit 1
    monkeypatch.setattr(kb, "process_job", _boom)
    assert kb.run_batch([(9, "x")]) == 1
