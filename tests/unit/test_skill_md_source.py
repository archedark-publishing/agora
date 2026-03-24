from __future__ import annotations

from pathlib import Path

import httpx

import agora.main as main_module
from agora.main import app


async def test_skill_md_uses_openclaw_skill_source() -> None:
    expected_path = Path(".agents/skills/agora-agent-registry/SKILL.md").resolve()

    assert main_module.SKILL_MD_PATH == expected_path
    assert expected_path.exists()
    assert not Path("agora/skills/SKILL.md").exists()

    expected = expected_path.read_text(encoding="utf-8")
    if not expected.endswith("\n"):
        expected = f"{expected}\n"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/skill.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == expected
    assert response.text.startswith("---\nname: agora-agent-registry\n")
    assert "POST \"$AGORA_URL/api/v1/agents/preflight\"" in response.text
    assert len(response.text) > 10_000
