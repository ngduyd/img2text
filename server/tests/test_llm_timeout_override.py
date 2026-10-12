"""Review R1 P2: render/proofread đọc llm_timeout qua runtime override."""

from app.core.models import Setting
from app.services import proofread, render_docx, render_md

class _RecClient:
    """AsyncClient ghi lại kwargs (timeout) → trả items rỗng."""
    timeouts: list = []

    def __init__(self, *args, **kwargs):
        _RecClient.timeouts.append(kwargs.get("timeout"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        from tests.test_export_llm_docx import FakeResponse

        return FakeResponse('{"items": []}')

async def test_llm_config_reads_runtime_timeout(db_session, monkeypatch):
    db_session.add(Setting(key="llm_timeout", value="333"))
    await db_session.commit()
    for mod in (render_docx, render_md):
        _base, _m, _k, timeout = await mod._llm_config()
        assert timeout == 333, mod.__name__

async def test_proofread_reads_runtime_timeout(db_session, monkeypatch):
    db_session.add(Setting(key="llm_timeout", value="444"))
    await db_session.commit()
    _RecClient.timeouts = []
    monkeypatch.setattr(proofread, "AsyncClient", _RecClient)
    await proofread._call_llm("text", "hint")
    assert _RecClient.timeouts == [444]
