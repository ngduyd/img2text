"""kcompat unit tests — hasattr dispatch: new / legacy / neither (RuntimeError)."""
import sys
from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEPLOY_DIR))

import kcompat  # noqa: E402

REF = "alice/ds-slug"

class NewApi:
    def __init__(self):
        self.calls = []

    def dataset_create_new(self, folder):
        self.calls.append(("create_new", folder))

    def dataset_create_version(self, folder, version_notes):
        self.calls.append(("create_version", folder, version_notes))

    def dataset_delete(self, owner_slug, dataset_slug, no_confirm=False):
        self.calls.append(("delete", owner_slug, dataset_slug, no_confirm))
        return True

    def dataset_list(self, search=None):
        self.calls.append(("list", search))
        return [{"ref": REF}]

class LegacyApi:
    def __init__(self):
        self.calls = []

    def datasets_create_with_files(self, upload_folder=None):
        self.calls.append(("create_with_files", upload_folder))

    def datasets_create_version(self, owner, slug, version_note=""):
        self.calls.append(("create_version", owner, slug, version_note))

    def datasets_delete(self, ref):
        self.calls.append(("delete", ref))
        return True

    def dataset_list(self, search=None):
        self.calls.append(("list", search))
        return [{"ref": REF}]

class NeitherApi:
    pass

def test_create_dispatch():
    new, legacy = NewApi(), LegacyApi()
    kcompat.api_create_dataset(new, "/tmp/x")
    kcompat.api_create_dataset(legacy, "/tmp/x")
    assert new.calls == [("create_new", "/tmp/x")]
    assert legacy.calls == [("create_with_files", "/tmp/x")]

def test_version_dispatch():
    new, legacy = NewApi(), LegacyApi()
    kcompat.api_version_dataset(new, "/tmp/x", REF, "notes")
    kcompat.api_version_dataset(legacy, "/tmp/x", REF, "notes")
    assert new.calls == [("create_version", "/tmp/x", "notes")]
    assert legacy.calls == [("create_version", "alice", "ds-slug", "notes")]

def test_delete_dispatch():
    new, legacy = NewApi(), LegacyApi()
    assert kcompat.api_delete_dataset(new, REF) is True
    assert kcompat.api_delete_dataset(legacy, REF) is True
    assert new.calls == [("delete", "alice", "ds-slug", True)]
    assert legacy.calls == [("delete", REF)]

def test_delete_neither_best_effort_false():
    # no delete API in either generation (real kaggle 1.6–1.8) → False, no raise
    assert kcompat.api_delete_dataset(NeitherApi(), REF) is False

def test_exists_dispatch():
    new, legacy = NewApi(), LegacyApi()
    assert kcompat.api_dataset_exists(new, REF) is True
    assert kcompat.api_dataset_exists(legacy, REF) is True
    assert new.calls == [("list", "ds-slug")]
    assert legacy.calls == [("list", "ds-slug")]

def test_exists_slug_only_row_and_owner_match():
    class SlugApi:
        def dataset_list(self, search=None):
            return [{"ref": "ds-slug"}]  # legacy row without owner

    class OwnedApi:
        def dataset_list(self, search=None):
            o = type("D", (), {"ref": "ds-slug", "owner_ref": "alice"})()
            return [o]

    assert kcompat.api_dataset_exists(SlugApi(), REF) is True
    assert kcompat.api_dataset_exists(OwnedApi(), REF) is True

def test_exists_no_match():
    api = NewApi()
    api.dataset_list = lambda search=None: [{"ref": "bob/other"}]
    assert kcompat.api_dataset_exists(api, REF) is False

def test_neither_raises_runtime_error():
    for fn, args in (
        (kcompat.api_create_dataset, ("/tmp/x",)),
        (kcompat.api_version_dataset, ("/tmp/x", REF, "n")),
        (kcompat.api_dataset_exists, (REF,)),
    ):
        with pytest.raises(RuntimeError, match="kaggle package"):
            fn(NeitherApi(), *args)
