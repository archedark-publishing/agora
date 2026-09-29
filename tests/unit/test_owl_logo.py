from __future__ import annotations

import importlib.util
import re
import sys
import xml.dom.minidom
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = REPO_ROOT / "agora" / "static"

# scripts/ is not a package, so load the generator by path.
_spec = importlib.util.spec_from_file_location("build_owl_logo", REPO_ROOT / "scripts" / "build_owl_logo.py")
build_owl_logo = importlib.util.module_from_spec(_spec)
sys.modules["build_owl_logo"] = build_owl_logo  # dataclasses look the module up by name
_spec.loader.exec_module(build_owl_logo)

LAYER_IDS = ["talons", "body", "wings", "wing-left", "wing-right", "crown", "ear-tufts", "brow", "eyes", "beak"]


@pytest.mark.parametrize("name", ["agora-logo.svg", "agora-favicon.svg"])
def test_generated_svg_is_clean_and_layered(name: str) -> None:
    svg = build_owl_logo.outputs()[name]
    xml.dom.minidom.parseString(svg)

    assert 'viewBox="0 0 1024 1024"' in svg
    for tag in ("<image", "<filter", "base64", "<text", "<use"):
        assert tag not in svg
    for layer in LAYER_IDS:
        assert 'id="%s"' % layer in svg
    ids = re.findall(r' id="([^"]+)"', svg)
    assert len(ids) == len(set(ids)), "duplicate ids"
    referenced = set(re.findall(r"url\(#([^)]+)\)", svg))
    assert referenced <= set(ids), "dangling url(#...) reference"


def test_favicon_drops_fine_detail() -> None:
    logo = build_owl_logo.outputs()["agora-logo.svg"]
    favicon = build_owl_logo.outputs()["agora-favicon.svg"]
    for detail in ("cheek-strip", "cheek-facet", "bib-stripe"):
        assert detail in logo
        assert detail not in favicon


def test_committed_svgs_match_generator() -> None:
    # Fails when someone edits scripts/build_owl_logo.py without regenerating, or hand-edits an SVG.
    # Fix: python scripts/build_owl_logo.py --png
    for name, svg in build_owl_logo.outputs().items():
        assert (STATIC / name).read_text() == svg, "%s is stale; rerun scripts/build_owl_logo.py" % name


def test_base_template_icon_links_point_at_real_files() -> None:
    base = (REPO_ROOT / "agora" / "templates" / "base.html").read_text()
    icons = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]*href="/static/([^"]+)"', base)
    assert set(icons) == {"agora-favicon.svg", "agora-favicon.png", "apple-touch-icon.png"}
    for icon in icons:
        assert (STATIC / icon).is_file()
