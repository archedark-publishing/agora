from __future__ import annotations


async def test_skill_md_endpoint_returns_markdown_with_frontmatter(client) -> None:
    response = await client.get("/skill.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")

    text = response.text
    assert text.startswith("---\n")
    assert "name: agent-agora" in text
    assert "version:" in text
    assert "description:" in text
    assert "homepage: http://testserver" in text

    assert "POST http://testserver/api/v1/agents" in text
    assert "GET http://testserver/api/v1/agents" in text
    assert "PUT http://testserver/api/v1/agents/{agent_id}" in text
    assert "DELETE http://testserver/api/v1/agents/{agent_id}" in text
    assert "X-API-Key" in text
    assert "http://testserver/docs" in text


async def test_homepage_footer_links_to_skill_markdown(client) -> None:
    home = await client.get("/")

    assert home.status_code == 200
    assert 'href="/skill.md"' in home.text
