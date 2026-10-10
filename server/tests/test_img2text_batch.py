"""Kernel unit tests (spec 2026-10-09 batch one-run + spec 2026-10-10 F3
manifest dual-mode: fetch_input download + sha256 verify, load_manifest,
mount fallback). find_inputs parses the
{job_id}__ staging prefix (sorted, dirs/unknown ext/non-prefixed skipped with
a log); run_batch continues past a failing job and sets the exit code from
outputs written. The module is imported DIRECTLY (import stays stdlib-only —
the pip/apt/venv bootstrap + heavy deps run only as __main__), no Kaggle."""

import functools
import hashlib
import http.server
import json
import sys
import threading
from pathlib import Path

import pytest

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

# --- F3 (spec 2026-10-10): manifest dual-mode — URL download + sha256
# verify / mount fallback. Local http.server = offline unit, no network. ---

@pytest.fixture
def served_file(tmp_path):
    payload = b"%PDF-1.4 fake bytes"
    (tmp_path / "doc.pdf").write_bytes(payload)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", payload
    server.shutdown()

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def test_fetch_input_downloads_and_verifies_sha256(served_file, tmp_path):
    base, payload = served_file
    dest = tmp_path / "dl" / "1__doc.pdf"  # parent dir chưa có → fetch tạo
    kb.fetch_input(f"{base}/doc.pdf", str(dest), _sha(payload))
    assert dest.read_bytes() == payload

def test_fetch_input_sha256_mismatch_removes_dest(served_file, tmp_path):
    base, _ = served_file
    dest = tmp_path / "2__doc.pdf"
    with pytest.raises(RuntimeError):
        kb.fetch_input(f"{base}/doc.pdf", str(dest), "0" * 64)
    assert not dest.exists()

def test_fetch_input_http_error_raises(tmp_path):
    with pytest.raises(Exception):
        kb.fetch_input(
            "http://127.0.0.1:9/missing.pdf", str(tmp_path / "x.pdf"), None, timeout=2
        )

def test_manifest_dual_mode_downloads_and_falls_back_to_mount(served_file, tmp_path):
    base, payload = served_file
    mount = tmp_path / "input"
    mount.mkdir()
    (mount / "9__legacy.pdf").write_bytes(b"legacy")  # dev mount fallback
    jobs = [
        {"job_id": 1, "input_url": f"{base}/doc.pdf", "filename": "1__doc.pdf",
         "sha256": _sha(payload)},                      # URL mode
        {"job_id": 2, "input_url": f"{base}/missing.pdf", "filename": "2__x.pdf",
         "sha256": None},                               # 404 → không fallback → bỏ qua
        {"job_id": 9, "input_url": f"{base}/missing.pdf", "filename": "9__x.pdf",
         "sha256": None},                               # 404 → mount fallback
    ]
    (mount / "manifest.json").write_text(json.dumps({"jobs": jobs}))
    assert kb.load_manifest(str(mount)) == jobs
    got = kb.fetch_manifest_jobs(jobs, str(tmp_path / "dl"), root=str(mount))
    assert [job_id for job_id, _ in got] == [1, 9]
    assert Path(got[0][1]).read_bytes() == payload  # download + verify
    assert got[1][1].endswith("9__legacy.pdf")      # mount fallback

def test_no_manifest_is_mount_fallback_mode(tmp_path):
    (tmp_path / "5__a.pdf").write_bytes(b"x")
    assert kb.load_manifest(str(tmp_path)) is None
    assert kb.find_inputs(str(tmp_path)) == [(5, str(tmp_path / "5__a.pdf"))]
