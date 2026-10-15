"""Lane K: GET /api/admin/kaggle-quota — parse quota_view() → giây."""

import sys
import types
from types import SimpleNamespace

import pytest

QUOTA_RESPONSE = SimpleNamespace(
    gpuQuota=SimpleNamespace(
        timeUsed="5900.915.0s",
        timeReserved="0s",
        totalTimeAllowed="21600.0s",
        minimumTimeAllowed="3600.0s",
        hasEverRun=True,
    ),
    tpuQuota=SimpleNamespace(
        timeUsed="7200.5s",
        timeReserved="0s",
        totalTimeAllowed="72000.0s",
        minimumTimeAllowed="0s",
        hasEverRun=True,
    ),
    quotaRefreshTime="2026-10-20T00:00:00Z",
)


class StubKaggleApi:
    """Stand-in for kaggle.api.kaggle_api_extended.KaggleApi (2.2.4)."""

    response = QUOTA_RESPONSE
    error: Exception | None = None

    def authenticate(self) -> None:
        pass

    def quota_view(self):
        if StubKaggleApi.error is not None:
            raise StubKaggleApi.error
        return StubKaggleApi.response


def _install_kaggle(monkeypatch) -> None:
    """Fake kaggle package in sys.modules (monkeypatched → auto-restored)."""
    pkg = types.ModuleType("kaggle")
    api_pkg = types.ModuleType("kaggle.api")
    ext = types.ModuleType("kaggle.api.kaggle_api_extended")
    ext.KaggleApi = StubKaggleApi
    pkg.api = api_pkg
    api_pkg.kaggle_api_extended = ext
    monkeypatch.setitem(sys.modules, "kaggle", pkg)
    monkeypatch.setitem(sys.modules, "kaggle.api", api_pkg)
    monkeypatch.setitem(sys.modules, "kaggle.api.kaggle_api_extended", ext)


async def test_kaggle_quota_parses_seconds(admin_client, monkeypatch):
    _install_kaggle(monkeypatch)
    r = await admin_client.get("/api/admin/kaggle-quota")
    assert r.status_code == 200, r.text
    body = r.json()
    gpu = body["gpu"]
    # "5900.915.0s" (malformed double-dot) → leading number 5900.915
    assert gpu["used_s"] == pytest.approx(5900.915)
    assert gpu["total_s"] == pytest.approx(21600.0)
    assert gpu["remaining_s"] == pytest.approx(15699.085)
    assert gpu["refresh"] == "2026-10-20T00:00:00Z"
    tpu = body["tpu"]
    assert tpu["used_s"] == pytest.approx(7200.5)
    assert tpu["total_s"] == pytest.approx(72000.0)
    assert tpu["refresh"] == "2026-10-20T00:00:00Z"


async def test_kaggle_quota_inner_snake_case_kagglesdk(admin_client, monkeypatch):
    """kaggle thật: inner ApiAcceleratorQuota chỉ snake_case (top-level có camelCase alias)."""
    _install_kaggle(monkeypatch)
    StubKaggleApi.response = SimpleNamespace(
        gpuQuota=SimpleNamespace(
            time_used="7664.478.0s", time_reserved="0s", total_time_allowed="21600s",
            minimum_time_allowed="21600s", has_ever_run=True,
        ),
        tpuQuota=SimpleNamespace(
            time_used="0s", time_reserved="0s", total_time_allowed="72000s",
            minimum_time_allowed="0s", has_ever_run=False,
        ),
        quotaRefreshTime="2026-10-17T00:00:00.000Z",
    )
    try:
        r = await admin_client.get("/api/admin/kaggle-quota")
        assert r.status_code == 200, r.text
        gpu = r.json()["gpu"]
        assert gpu["used_s"] == pytest.approx(7664.478)
        assert gpu["total_s"] == pytest.approx(21600.0)
        assert gpu["remaining_s"] == pytest.approx(13935.522)
    finally:
        StubKaggleApi.response = QUOTA_RESPONSE

async def test_kaggle_quota_missing_refresh_field_null_not_502(admin_client, monkeypatch):
    """P2-1: field thiếu CẢ camelCase lẫn snake_case → null (UI hiển thị "—"), không 502."""
    _install_kaggle(monkeypatch)
    StubKaggleApi.response = SimpleNamespace(
        gpuQuota=SimpleNamespace(
            timeUsed="100s", timeReserved="0s", totalTimeAllowed="21600s",
            minimumTimeAllowed="3600s", hasEverRun=True,
        ),
        tpuQuota=SimpleNamespace(
            timeUsed="0s", timeReserved="0s", totalTimeAllowed="72000s",
            minimumTimeAllowed="0s", hasEverRun=False,
        ),
        # quotaRefreshTime missing — neither camelCase nor snake_case
    )
    try:
        r = await admin_client.get("/api/admin/kaggle-quota")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["gpu"]["refresh"] is None
        assert body["tpu"]["refresh"] is None
        assert body["gpu"]["total_s"] == pytest.approx(21600.0)
    finally:
        StubKaggleApi.response = QUOTA_RESPONSE

async def test_kaggle_quota_admin_only(auth_client, monkeypatch):
    _install_kaggle(monkeypatch)
    assert (await auth_client.get("/api/admin/kaggle-quota")).status_code == 403

async def test_kaggle_quota_unauth_401(client, monkeypatch):
    _install_kaggle(monkeypatch)
    assert (await client.get("/api/admin/kaggle-quota")).status_code == 401


async def test_kaggle_quota_missing_package_503(admin_client, monkeypatch):
    for name in ("kaggle", "kaggle.api", "kaggle.api.kaggle_api_extended"):
        monkeypatch.setitem(sys.modules, name, None)  # None → ImportError
    r = await admin_client.get("/api/admin/kaggle-quota")
    assert r.status_code == 503
    assert "kaggle" in r.json()["detail"].lower()


async def test_kaggle_quota_api_error_502(admin_client, monkeypatch):
    _install_kaggle(monkeypatch)
    StubKaggleApi.error = OSError("quota endpoint down")
    try:
        r = await admin_client.get("/api/admin/kaggle-quota")
        assert r.status_code == 502
        # P2: generic detail — không echo raw exc (leak paths/keys); exc đầy đủ ở log
        assert "quota endpoint down" not in r.json()["detail"]
    finally:
        StubKaggleApi.error = None
