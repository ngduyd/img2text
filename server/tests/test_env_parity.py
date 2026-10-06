"""Env parity (Plan G Task 1): deploy/.env.example keys == Settings fields.

Single source is Settings (server/app/config.py); .env.example may not drift
in either direction — missing keys break deploy, stale keys lie to operators.
"""

from pathlib import Path

from app.core.config import Settings


def test_env_example_matches_settings_fields():
    fields = {n.upper() for n in Settings.model_fields}
    example = Path(__file__).parents[2] / "deploy" / ".env.example"
    keys = {ln.split("=")[0].strip() for ln in example.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")}
    assert fields <= keys, f"missing in .env.example: {fields - keys}"
    assert keys <= fields, f"stale keys in .env.example: {keys - fields}"
