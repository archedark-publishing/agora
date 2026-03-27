from __future__ import annotations

import ast
from pathlib import Path


MAIN_MODULE_PATH = Path(__file__).resolve().parents[2] / "agora" / "main.py"


def _template_response_calls() -> list[ast.Call]:
    tree = ast.parse(MAIN_MODULE_PATH.read_text())
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "TemplateResponse":
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "templates":
            continue
        calls.append(node)
    return calls


def test_template_response_calls_use_starlette_v1_signature() -> None:
    calls = _template_response_calls()
    assert len(calls) == 11, "Expected 11 TemplateResponse calls in agora/main.py"

    for call in calls:
        assert call.args, "TemplateResponse call must include positional args"
        assert isinstance(call.args[0], ast.Name) and call.args[0].id == "request"
        assert len(call.args) >= 2, "TemplateResponse call must include template name"
        assert isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str)

        context_keyword = next((kw for kw in call.keywords if kw.arg == "context"), None)
        assert context_keyword is not None, "TemplateResponse call must pass context=..."
        assert isinstance(context_keyword.value, ast.Dict)
