from __future__ import annotations

from pathlib import Path

import agora.main as main_module


async def test_skill_md_endpoint_serves_repo_skill_file(client) -> None:
    response = await client.get("/skill.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")

    expected = Path(
        ".agents/skills/agora-agent-registry/SKILL.md"
    ).read_text(encoding="utf-8")
    if not expected.endswith("\n"):
        expected = f"{expected}\n"

    assert response.text == expected


async def test_skill_md_endpoint_falls_back_when_skill_file_missing(client, monkeypatch) -> None:
    missing_path = Path("/tmp/does-not-exist-skill.md")
    monkeypatch.setattr(main_module, "SKILL_MD_PATH", missing_path)

    response = await client.get("/skill.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == main_module.SKILL_MD_FALLBACK
    assert "github.com/archedark-publishing/agora" in response.text


async def test_homepage_footer_links_to_skill_markdown(client) -> None:
    home = await client.get("/")

    assert home.status_code == 200
    assert 'href="/skill.md"' in home.text
