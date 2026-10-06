"""kaggle package API compat layer (deploy scripts).

kaggle 2.2.x exposes dataset_create_new / dataset_create_version /
dataset_delete / dataset_list; older or forked builds may only have the
legacy datasets_* names. hasattr dispatch: new name first, legacy
fallback, neither → RuntimeError("kaggle package: <name> not found —
cần kaggle>=1.6").

ponytail: legacy datasets_* branches are defensive only — no PyPI kaggle
release up to 2.2.4 defines them (verified 1.1.0…2.2.4); drop them when
forked/ancient packages are out of scope. Delete has NO legacy-safe path:
some real versions (1.6–1.8) lack any delete API → best-effort False.
"""
import sys


def api_create_dataset(api, folder):
    """Upload-create a dataset from `folder` (contains dataset-metadata.json)."""
    if hasattr(api, "dataset_create_new"):
        return api.dataset_create_new(str(folder))
    if hasattr(api, "datasets_create_with_files"):
        return api.datasets_create_with_files(upload_folder=str(folder))
    raise RuntimeError("kaggle package: dataset_create_new not found — cần kaggle>=1.6")


def api_version_dataset(api, folder, ref, notes):
    """New dataset version uploading files from `folder`.

    new API uploads from folder; legacy splits ref into (owner, slug).
    """
    if hasattr(api, "dataset_create_version"):
        return api.dataset_create_version(str(folder), notes)
    if hasattr(api, "datasets_create_version"):
        owner, slug = ref.split("/", 1)
        return api.datasets_create_version(owner, slug, version_note=notes)
    raise RuntimeError(
        "kaggle package: dataset_create_version not found — cần kaggle>=1.6"
    )


def api_delete_dataset(api, ref):
    """Delete dataset `ref` ("owner/slug"). True = deleted (or attempted);
    False = no delete API (best-effort skip) or server declined.
    Exceptions from a present delete method propagate."""
    owner, slug = ref.split("/", 1)
    if hasattr(api, "dataset_delete"):
        result = api.dataset_delete(owner, slug, no_confirm=True)
        return result is not False  # 1.8-era returns None on success
    if hasattr(api, "datasets_delete"):
        result = api.datasets_delete(ref)
        return result is not False
    print(
        f"warning: kaggle package has no dataset delete API — skipping delete of {ref}",
        file=sys.stderr,
    )
    return False


def api_dataset_exists(api, ref):
    """Hasattr-verified exists check via dataset_list (both API generations).

    Old code try/except-ed the CREATE call and swallowed any exception
    (incl. AttributeError) as "exists" — that masked the renamed API.
    Returns True only on an exact ref match in the list results.
    """
    owner, slug = ref.split("/", 1)
    list_fn = getattr(api, "dataset_list", None)
    with_resp_fn = getattr(api, "dataset_list_with_response", None)
    if list_fn is None and with_resp_fn is None:
        raise RuntimeError("kaggle package: dataset_list not found — cần kaggle>=1.6")
    if list_fn is not None:
        items = list_fn(search=slug)
    else:
        resp = with_resp_fn(search=slug)
        items = getattr(resp, "datasets", None)
    for item in items or []:
        if isinstance(item, dict):
            raw = str(item.get("ref") or "")
            item_owner = str(item.get("owner") or item.get("owner_ref") or "")
        else:
            raw = str(getattr(item, "ref", "") or "")
            item_owner = str(getattr(item, "owner_ref", "") or "")
        if not raw:
            continue
        if "/" not in raw:
            # slug-only row: reattach owner when known
            raw = f"{item_owner}/{raw}" if item_owner else raw
        if raw.casefold() == ref.casefold():
            return True
        if "/" not in raw and raw.casefold() == slug.casefold():
            # owner unknown (legacy row) — slug match is the best signal
            return True
    return False
