"""P2 #20 (spec 2026-10-16): prod_only marker gating — skip khi env != "prod".

Hook chạy ở collection time (trước fixture) → self-test gọi trực tiếp
pytest_collection_modifyitems với stub item; `env` fixture đổi
settings.env cho đúng nhánh.
"""

from types import SimpleNamespace

import pytest

from tests import conftest


class _StubItem:
    def __init__(self, *marks):
        self._marks = list(marks)

    def get_closest_marker(self, name):
        return next((m for m in self._marks if m.name == name), None)

    def add_marker(self, marker):
        self._marks.append(marker)


def _skipped(item) -> bool:
    return any(m.name == "skip" for m in item._marks)


def test_prod_only_skipped_when_env_not_prod(env):
    env("test")
    item = _StubItem(pytest.mark.prod_only)
    conftest.pytest_collection_modifyitems(None, [item])
    assert _skipped(item)


def test_prod_only_runs_when_env_prod(env):
    env("prod")
    item = _StubItem(pytest.mark.prod_only)
    conftest.pytest_collection_modifyitems(None, [item])
    assert not _skipped(item)


def test_unmarked_test_never_skipped(env):
    env("test")
    item = _StubItem()
    conftest.pytest_collection_modifyitems(None, [item])
    assert not _skipped(item)
