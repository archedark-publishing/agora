#!/usr/bin/env python3
"""Generate the Agora owl logo and favicon as hand-built SVG.

The owl is a clean vector rebuild of ``agora/static/agora-logo.png`` (the approved
design). It is authored from primitives (polygons, Catmull-Rom curves, ellipses and
circles), not auto-traced, so every node is deliberate.

Outputs (written to ``--out-dir``, default ``agora/static``):

    agora-logo.svg          full mark, all detail
    agora-favicon.svg       simplified cut for tab-size rendering
    agora-favicon.png       32x32 fallback for the favicon          (needs PNG deps)
    apple-touch-icon.png    180x180 on an opaque plate for iOS      (needs PNG deps)

Usage:

    python scripts/build_owl_logo.py               # SVGs only (stdlib, no dependencies)
    python scripts/build_owl_logo.py --png         # also render the PNGs
    python scripts/build_owl_logo.py --check       # exit 1 if the SVGs on disk are stale
    python scripts/build_owl_logo.py --source-space /tmp/dev.svg
                                                    # 1:1 with agora-logo.png pixels, for overlays

PNG rendering needs ``pip install resvg-py pillow``. They are deliberately not app
dependencies, so this stays a dev-time tool.

How the geometry is authored
----------------------------
* All coordinates below are in the pixel space of ``agora-logo.png`` (1024x1024).
* Only the LEFT half is authored. ``Side(1)`` mirrors it about the vertical axis
  ``AX``. ``AX`` (510.7) is not 512: it is the axis that best fits the source art,
  which is slightly off-centre. The final transform re-centres it on x=512.
* Geometry is mirrored exactly, but fills are not. The source is lit from the right,
  so left-half plates are darker. Fills that differ per side are given as
  ``(left, right)`` tuples. The highlight dots are translated, not mirrored (both
  sit at the upper-left of their pupil, as in the source).
* Curved edges are ``smooth([...])`` through a few measured points. Straight edges
  are ``poly([...])``. Points on the axis use ``AX`` so centre seams stay exact.
* Ink outlines are separate black shapes under each plate (a stroked copy of the
  plate outline), never a stroke on the plate itself, because SVG strokes are
  centred and would eat into the fill.

Layers, back to front (each is a group with an id, so the animation team can address
it): talons, body, wings (wing-left / wing-right), crown, ear-tufts (ear-tuft-left /
ear-tuft-right), brow, eyes (eye-left / eye-right), beak. Wings and ear tufts carry
``data-pivot`` plus an inline ``transform-origin`` so CSS/JS can rotate them from the
shoulder / base without extra setup.

Variants
--------
``LOGO``     full detail, 24-unit ink, fitted with a margin inside the viewBox.
``FAVICON``  drops cheek strips/facets, eye-interior shading and the small bib/collar
             stripes; 34-unit ink; larger eye highlights; fitted almost edge to edge.
``TOUCH``    the favicon art on an opaque square plate (iOS fills transparency with
             black, which would swallow the outline).

Palette
-------
Sampled from the source PNG (k-means centroids), so it is more saturated than the
generic brand ramp. ``P`` below names the main steps. Gradients are linear, subtle and
sampled; the ear/brow blade fades sky to white horizontally because that is what the
source does, every other gradient is vertical.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.dom.minidom
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "agora" / "static"

AX = 510.7  # mirror axis in source (PNG) coordinates

P = dict(
    ink="#02040A", ice="#F0FBFB", palei="#C9EAF7", pale="#9CD4F1", skyl="#64BBF2",
    sky="#36A2EC", royal="#0C6EC2", deep="#09549F", navy="#083671", abyss="#0A1C36",
)


# ---------------------------------------------------------------------------
# Fit and variants
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fit:
    """Map source space to viewBox space: X = ox + s*(x - cx), Y = oy + s*(y - cy)."""

    s: float
    cx: float
    cy: float
    ox: float = 512.0
    oy: float = 512.0

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return (self.ox + self.s * (x - self.cx), self.oy + self.s * (y - self.cy))


@dataclass(frozen=True)
class Variant:
    fav: bool = False        # simplified favicon detail level
    ink: float = 24          # ink outline width (half of it shows outside each plate)
    talon_ink: float = 26
    fit: Fit = Fit(0.96, AX, 516.5)
    plate: str | None = None  # opaque square background colour
    header: str = ""          # XML comment placed after <title>


# Art bounds in source space are x 60..960, y 17..1016 (centre y 516.5).
LOGO = Variant(
    header=(
        "<!-- Layers (back to front): talons, body, wings (wing-left / wing-right, pivot at shoulder), "
        "crown, ear-tufts, brow, eyes, beak.\n"
        "     Geometry is mirrored about x=512; light/dark fills follow the source lighting (left half darker). -->\n"
    ),
)
FAVICON = Variant(fav=True, ink=34, talon_ink=38, fit=Fit(0.99, AX, 516.5))
TOUCH = Variant(fav=True, ink=34, talon_ink=38, fit=Fit(0.84, AX, 516.5), plate="#EAF3FB")
SOURCE_SPACE = Variant(fit=Fit(1.0, 510, 510, 510, 510))


# ---------------------------------------------------------------------------
# Path model: a path is a list of (command, [points]) in source space
# ---------------------------------------------------------------------------
def M(p):
    return ("M", [p])


def L(*ps):
    return ("L", list(ps))


def C(a, b, c):
    return ("C", [a, b, c])


def Z():
    return ("Z", [])


def poly(pts, close=True):
    cmds = [M(pts[0])] + [L(p) for p in pts[1:]]
    if close:
        cmds.append(Z())
    return cmds


def smooth(pts, tension=1.0, first_cmd="M"):
    """Catmull-Rom spline through ``pts`` as cubic Beziers (tension 1.0 = standard)."""
    k = tension / 6.0
    cmds = [M(pts[0]) if first_cmd == "M" else L(pts[0])]
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else pts[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k)
        c2 = (p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k)
        cmds.append(C(c1, c2, p2))
    return cmds


def smooth_closed(pts, tension=1.0):
    n = len(pts)
    k = tension / 6.0
    cmds = [M(pts[0])]
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k)
        c2 = (p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k)
        cmds.append(C(c1, c2, p2))
    cmds.append(Z())
    return cmds


def join(*parts):
    out = []
    for part in parts:
        out.extend(part)
    return out


def drop_move(cmds):
    return cmds[1:] if cmds and cmds[0][0] == "M" else cmds


def mir_pt(p):
    return (2 * AX - p[0], p[1])


def mirror_cmds(cmds):
    return [(c, [mir_pt(p) for p in ps]) for c, ps in cmds]


def sym_poly(left):
    """Closed symmetric polygon from left-half points running axis-top to axis-bottom."""
    right = [mir_pt(p) for p in reversed(left)]
    return poly(list(left) + right[1:-1])


def fmt(v: float) -> str:
    v = round(v, 1)
    return ("%d" % v) if v == int(v) else ("%.1f" % v)


def attrs(**kw) -> str:
    return " ".join('%s="%s"' % (k.replace("_", "-"), v) for k, v in kw.items() if v is not None)


# ---------------------------------------------------------------------------
# Geometry (source space, left half; see module docstring)
# ---------------------------------------------------------------------------
# Ear tuft + brow are one sweep ("blade"), split at SEAM so they can animate separately.
BLADE_UP = [(84, 112), (140, 161), (184, 182), (262, 207), (345, 232), (410, 267), (472, 331), (AX, 420)]
BLADE_LO = [(84, 114), (99, 157), (121, 196), (147, 225), (177, 247), (207, 263), (251, 279), (300, 288),
            (342, 294), (416, 329), (457, 385), (470, 450)]
SEAM = 262

# Eyes: the ring is a tilted ellipse; the sclera is a small closed spline because its
# upper-left bulges past any ellipse fit. Pupil is a circle offset toward the centre.
EYE_RING = dict(cx=331.5, cy=417.0, a=145.4, b=122.9, rot=41.1)
PUPIL = (352, 401, 77)
SCLERA = smooth_closed([(268, 308), (236, 349), (226, 394), (233, 441), (257, 482), (311, 517), (378, 521),
                        (423, 498), (446, 455), (432, 395), (385, 338), (305, 310)])
HIGHLIGHT = {0: (316.5, 373, 21), 1: (633, 373, 21)}

WING_OUT = [(128, 518), (112, 547), (95, 585), (83, 620), (74, 660), (73, 700), (80, 750), (96, 790), (120, 828),
            (150, 865), (190, 905), (240, 948), (290, 978), (322, 998)]
WING_IN = [(322, 998), (315, 982), (277, 871), (266, 822), (247, 740), (224, 588)]

# (left edge through-points, top-right corner, (left fill, right fill))
TALONS = [
    ([(342, 929), (352, 962), (372, 984), (394, 998)], (377, 934), ("#0469C8", "#1077CF")),
    ([(394, 934), (400, 962), (418, 987), (446, 1004)], (427, 934), ("#2C99E7", "#1993E0")),
    ([(450, 933), (458, 962), (474, 988), (496, 1002)], (484, 933), ("#C7F3FC", "#8ED3FB")),
]


def blade_cmds():
    return join(smooth(BLADE_UP), [L((AX, 456)), L((472, 458))],
                drop_move(smooth(list(reversed(BLADE_LO)), first_cmd="L")), [Z()])


def wing_cmds():
    return join(smooth(WING_OUT), drop_move(smooth(WING_IN, first_cmd="L")), [L((128, 518)), Z()])


# ---------------------------------------------------------------------------
# SVG emission
# ---------------------------------------------------------------------------
class Builder:
    def __init__(self, variant: Variant):
        self.v = variant
        self.fit = variant.fit
        self.defs: list[str] = []
        self.sides = (Side(self, 0), Side(self, 1))

    # -- primitives -------------------------------------------------------
    def d(self, cmds) -> str:
        out = []
        for c, ps in cmds:
            if c == "Z":
                out.append("Z")
            else:
                out.append(c + " ".join("%s,%s" % tuple(fmt(v) for v in self.fit.pt(*p)) for p in ps))
        return "".join(out)

    def path(self, cmds, id=None, **kw) -> str:
        extra = attrs(**kw)
        return '<path %sd="%s"%s/>' % (('id="%s" ' % id) if id else "", self.d(cmds), (" " + extra) if extra else "")

    def ellipse(self, cx, cy, rx, ry, rot=0.0, **kw) -> str:
        X, Y = self.fit.pt(cx, cy)
        tr = ' transform="rotate(%s %s %s)"' % (fmt(rot), fmt(X), fmt(Y)) if rot else ""
        return '<ellipse cx="%s" cy="%s" rx="%s" ry="%s"%s %s/>' % (
            fmt(X), fmt(Y), fmt(rx * self.fit.s), fmt(ry * self.fit.s), tr, attrs(**kw))

    def circle(self, cx, cy, r, **kw) -> str:
        X, Y = self.fit.pt(cx, cy)
        return '<circle cx="%s" cy="%s" r="%s" %s/>' % (fmt(X), fmt(Y), fmt(r * self.fit.s), attrs(**kw))

    def sw(self, v) -> str:
        return fmt(v * self.fit.s)

    def _grad(self, gid, x1, y1, x2, y2, stops) -> str:
        X1, Y1 = self.fit.pt(x1, y1)
        X2, Y2 = self.fit.pt(x2, y2)
        st = "".join('<stop offset="%s" stop-color="%s"/>' % s for s in stops)
        return ('<linearGradient id="%s" gradientUnits="userSpaceOnUse" x1="%s" y1="%s" x2="%s" y2="%s">%s'
                '</linearGradient>' % (gid, fmt(X1), fmt(Y1), fmt(X2), fmt(Y2), st))

    def vgrad(self, name, y1, y2, stops) -> str:
        """Vertical gradient shared by both sides (x is irrelevant). Returns a fill url."""
        if not any(d.startswith('<linearGradient id="%s"' % name) for d in self.defs):
            self.defs.append(self._grad(name, 0, y1, 0, y2, stops))
        return "url(#%s)" % name

    def hgrad(self, name, x1, x2, stops):
        """Horizontal gradient authored on the left, emitted mirrored for the right."""
        self.defs.append(self._grad(name + "-l", x1, 0, x2, 0, stops))
        self.defs.append(self._grad(name + "-r", 2 * AX - x1, 0, 2 * AX - x2, 0, stops))
        return ("url(#%s-l)" % name, "url(#%s-r)" % name)

    def clip_rect(self, cid, x_left_src, x_right_src) -> None:
        x0 = self.fit.pt(x_left_src, 0)[0]
        x1 = self.fit.pt(x_right_src, 0)[0]
        self.defs.append('<clipPath id="%s"><rect x="%s" y="0" width="%s" height="1024"/></clipPath>' % (
            cid, fmt(x0), fmt(x1 - x0)))

    def pivot_group(self, gid, src_pt) -> str:
        px, py = self.fit.pt(*src_pt)
        return '<g id="%s" data-pivot="%s %s" style="transform-box:view-box;transform-origin:%spx %spx">' % (
            gid, fmt(px), fmt(py), fmt(px), fmt(py))

    # -- components (z-order is set in build()) ---------------------------
    def crown(self) -> str:
        ink, w = P["ink"], self.sw(self.v.ink)
        o = ['<g id="crown">']
        # Black backing under the frieze.
        o.append(self.path(sym_poly([(AX, 150), (207, 150), (207, 182), (300, 222), (400, 258), (AX, 290)]), fill=ink))
        # Pediment cap: ink outline layer, then the ice fill.
        ped = sym_poly([(AX, 29), (172, 113), (182, 138), (AX, 138)])
        o.append(self.path(ped, id="pediment-ink", fill=ink, stroke=ink, stroke_width=w, stroke_linejoin="round"))
        o.append(self.path(ped, id="pediment", fill=P["ice"]))
        g = self.vgrad("g-tym", 58, 106, [(0, P["royal"]), (1, P["deep"])])
        o.append(self.path(sym_poly([(AX, 58), (345, 106), (AX, 106)]), id="tympanum", fill=g))
        # Entablature band with end caps.
        g2 = self.vgrad("g-ent", 139, 163, [(0, P["deep"]), (0.3, P["royal"]), (0.75, P["royal"]), (1, P["deep"])])
        ent = sym_poly([(AX, 139), (220, 139), (220, 164), (283, 190), (283, 162), (AX, 162)])
        o.append(self.path(ent, id="entablature", fill=g2))
        # Triglyph-like light segments.
        for s in self.sides:
            o.append(s.path(poly([(348, 166), (413, 166), (413, 225), (348, 209)]), id="frieze-seg", fill=P["pale"]))
        o.append(self.path(sym_poly([(AX, 164), (477, 164), (477, 237), (AX, 246)]), id="frieze-seg-c", fill=P["pale"]))
        o.append("</g>")
        return "\n".join(o)

    def ear_tufts(self) -> str:
        ink, w = P["ink"], self.sw(self.v.ink)
        grad_l, grad_r = self.hgrad("g-blade", 88, 440, [
            (0, "#33A0F0"), (0.23, "#4EAEF5"), (0.375, "#6CC0F4"), (0.545, "#97D5F7"), (0.69, "#B2DFFA"),
            (0.83, "#D0EDFC"), (1, P["ice"])])
        self.clip_rect("clip-tuft-l", 0, SEAM)
        self.clip_rect("clip-tuft-r", 2 * AX - SEAM, 1024)
        o = ['<g id="ear-tufts">']
        for s in self.sides:
            o.append(self.pivot_group("ear-tuft-%s" % s.name, s.pt((262, 245))))
            o.append(s.path(blade_cmds(), id="tuft-ink", fill=ink, stroke=ink, stroke_width=w, stroke_linejoin="round"))
            o.append(s.path(blade_cmds(), id="tuft", fill=(grad_l, grad_r), clip_path="url(#clip-tuft-%s)" % s.tag))
            o.append("</g>")
        o.append("</g>")
        return "\n".join(o)

    def brow(self) -> str:
        o = ['<g id="brow">']
        # Forehead V facets sit under the blade fill so the blade edge defines the seam.
        v = poly([(375, 242), (AX, 277), (AX, 428), (440, 330)])
        o.append(self.sides[0].path(v, id="forehead", fill=P["deep"]))
        o.append(self.sides[1].path(v, id="forehead", fill=P["royal"]))
        for s in self.sides:
            o.append(s.path(blade_cmds(), id="brow-plate", fill="url(#g-blade-%s)" % s.tag,
                            clip_path="url(#clip-brow-%s)" % s.tag))
        o.append("</g>")
        self.clip_rect("clip-brow-l", SEAM - 1.5, 1024)
        self.defs.append('<clipPath id="clip-brow-r"><rect x="0" y="0" width="%s" height="1024"/></clipPath>' % (
            fmt(self.fit.pt(2 * AX - SEAM + 1.5, 0)[0])))
        return "\n".join(o)

    def eyes(self) -> str:
        fav = self.v.fav
        o = ['<g id="eyes">']
        # Cheek arch plates (outside the ring).
        cheek_outer = [(157, 273), (146, 301), (138, 340), (134, 371), (134, 412), (142, 449), (157, 479),
                       (173, 502), (200, 535), (243, 557), (280, 569), (322, 574), (368, 572)]
        cheek = join(smooth(cheek_outer), [L((380, 540)), L((300, 470)), L((250, 380)), L((232, 330)),
                                           L((230, 302)), Z()])
        g_l = self.vgrad("g-cheek-l", 300, 573, [(0, "#2E86C8"), (0.3, "#3A98E4"), (1, "#66BAF0")])
        g_r = self.vgrad("g-cheek-r", 300, 573, [(0, "#9FD4EB"), (0.3, "#DBF2F7"), (1, "#F0FAFC")])
        strip = join(smooth([(152, 318), (150, 345), (151, 389), (160, 430), (181, 460), (206, 492), (237, 515),
                             (275, 534), (318, 552)]),
                     [L((320, 520)), L((250, 470)), L((215, 400)), L((215, 330)), Z()])
        g_strip = self.vgrad("g-strip", 318, 420, [(0, P["pale"]), (0.6, P["ice"]), (1, P["ice"])])
        ring = EYE_RING
        for s in self.sides:
            o.append('<g id="eye-%s">' % s.name)
            o.append(s.path(cheek, id="cheek", fill=(g_l, g_r)))
            if not fav:
                o.append(s.path(strip, id="cheek-strip", fill=g_strip))
                o.append(s.path(poly([(155, 275), (230, 302), (219, 317), (190, 315), (172, 296)]),
                                id="cheek-facet", fill="#1364AA"))
                o.append(s.path(poly([(186, 303), (216, 304), (213, 320), (199, 356), (196, 408), (188, 380),
                                      (186, 330)]), id="cheek-inner", fill="#1364AA"))
            o.append(s.ellipse(ring["cx"], ring["cy"], ring["a"], ring["b"], ring["rot"], fill=P["ink"]))
            o.append(s.path(SCLERA, id="sclera", fill=P["ice"]))
            # Interior shading, clipped to the sclera.
            cid = "clip-sclera-%s" % s.tag
            self.defs.append('<clipPath id="%s">%s</clipPath>' % (cid, s.path(SCLERA)))
            o.append('<g clip-path="url(#%s)">' % cid)
            if not fav:
                top = poly([(225, 382), (236, 358), (256, 352), (292, 348), (322, 328), (342, 319), (345, 280),
                            (200, 280)])
                o.append(s.path(top, fill=P["skyl"]))
                gr = self.vgrad("g-scl-right", 385, 510, [(0, P["skyl"]), (0.5, P["pale"]), (1, P["ice"])])
                right = poly([(432, 383), (415, 425), (392, 470), (372, 505), (372, 545), (480, 545), (480, 383)])
                o.append(s.path(right, fill=gr))
            o.append("</g>")
            o.append(s.circle(PUPIL[0], PUPIL[1], PUPIL[2], fill=P["ink"]))
            hx, hy, hr = HIGHLIGHT[s.i]
            o.append(self.circle(hx, hy, hr * (1.3 if fav else 1), fill=P["ice"]))
            o.append("</g>")
        o.append("</g>")
        return "\n".join(o)

    def beak(self) -> str:
        o = ['<g id="beak">']
        outer = [(AX, 437), (473, 449), (448, 490), (457, 545), (AX, 618)]
        mirrored = [mir_pt(p) for p in outer]
        ink = join(smooth(outer), drop_move(smooth(list(reversed(mirrored)), first_cmd="L")), [Z()])
        o.append(self.path(ink, id="beak-ink", fill=P["ink"]))
        inner = join(smooth([(AX, 462), (487, 473), (470, 503), (488, 546), (AX, 586)]), [Z()])
        g1 = self.vgrad("g-beak-l", 462, 586, [(0, "#0A55AA"), (1, "#053E86")])
        g2 = self.vgrad("g-beak-r", 462, 586, [(0, P["palei"]), (1, P["ice"])])
        o.append(self.path(inner, id="beak-half-l", fill=g1))
        o.append(self.path(mirror_cmds(inner), id="beak-half-r", fill=g2))
        o.append("</g>")
        return "\n".join(o)

    def body(self) -> str:
        fav = self.v.fav
        o = ['<g id="body">']
        # Black base behind head + torso (also fills the wedge above the wings).
        left = [(AX, 150), (207, 150), (207, 176), (155, 253), (140, 274), (131, 304), (122, 370), (127, 450),
                (141, 487), (108, 531), (140, 640), (200, 700), (300, 900), (330, 932), (AX, 932)]
        o.append(self.path(sym_poly(left), id="body-ink", fill=P["ink"]))
        # Face shield below the eyes, split light/dark at the axis.
        shield = poly([(322, 584), (340, 562), (370, 520), (430, 500), (AX, 500), (AX, 701)])
        gl = self.vgrad("g-shield-l", 550, 700, [(0, "#74C0F3"), (1, "#8FCEF5")])
        gr = self.vgrad("g-shield-r", 550, 700, [(0, "#E3F5FB"), (1, P["ice"])])
        for s in self.sides:
            o.append(s.path(shield, id="shield", fill=(gl, gr)))
        # Collar chevron band + end blocks.
        cg = self.hgrad("g-collar", 257, 510, [(0, "#0A66C0"), (0.55, "#1F86D8"), (1, "#5DB0EC")])
        cg_r = self.hgrad("g-collar-r", 257, 510, [(0, "#38A6F0"), (1, "#66B8EB")])
        band = poly([(257, 599), (AX, 703), (AX, 722), (321, 645)])
        for s in self.sides:
            o.append(s.path(band, id="collar", fill=(cg[0], cg_r[1])))
        end = poly([(257, 599), (321, 628), (325, 703), (267, 660)])
        for s in self.sides:
            o.append(s.path(end, id="collar-end", fill=("#0167BB", "#38ABF2")))
            if not fav:
                o.append(s.path(poly([(313, 640), (322, 644), (327, 704), (318, 698)]), fill=("#0A559B", "#2A9BE1")))
        # Bib (light V) with divider stripes.
        b1 = self.vgrad("g-bib-l", 650, 830, [(0, "#84CAF8"), (0.5, "#BDE3FD"), (1, "#A2D8F4")])
        b2 = self.vgrad("g-bib-r", 650, 830, [(0, "#D6EDFB"), (0.5, "#FAFFF9"), (1, "#E1F9FE")])
        bib = poly([(321, 645), (AX, 716), (AX, 851), (416, 774), (388, 752), (327, 704)])
        for s in self.sides:
            o.append(s.path(bib, id="bib", fill=(b1, b2)))
            if not fav:
                o.append(s.path(poly([(381, 674), (400, 681), (416, 775), (389, 752)]), id="bib-stripe",
                                fill=("#0574CA", "#2496EA")))
        # Navy chevron plates and the dark belly where they meet.
        n1 = self.vgrad("g-navy-l", 720, 918, [(0, "#062A66"), (0.65, "#033676"), (1, "#0B1B3F")])
        n2 = self.vgrad("g-navy-r", 720, 918, [(0, "#0357AB"), (0.5, "#04458C"), (0.78, "#01316E"), (1, "#03102A")])
        plate = poly([(283, 720), (496, 879), (438, 918), (305, 815)])
        for s in self.sides:
            o.append(s.path(plate, id="chevron", fill=(n1, n2)))
        belly = self.vgrad("g-belly", 880, 932, [(0, "#04122E"), (1, "#030C20")])
        o.append(self.path(poly([(499, 881), (521, 881), (583, 922), (583, 932), (437, 932), (437, 922)]),
                           id="belly", fill=belly))
        o.append("</g>")
        return "\n".join(o)

    def wings(self) -> str:
        ink, w = P["ink"], self.sw(self.v.ink)
        o = ['<g id="wings">']
        for s in self.sides:
            cid = "clip-wing-%s" % s.tag
            self.defs.append('<clipPath id="%s">%s</clipPath>' % (cid, s.path(wing_cmds())))
            o.append(self.pivot_group("wing-%s" % s.name, s.pt((190, 560))))
            o.append(s.path(wing_cmds(), id="wing-ink", fill=ink, stroke=ink, stroke_width=w, stroke_linejoin="round"))
            top_l = self.vgrad("g-wtop", 520, 650, [(0, "#095197"), (0.35, "#0364B9"), (0.75, "#037CD4"), (1, "#1180D8")])
            top_r = self.vgrad("g-wtop-r", 520, 650, [(0, "#3CA6E3"), (0.35, "#40B1F5"), (1, "#54B6F5")])
            o.append(s.path(wing_cmds(), id="wing-plate", fill=(top_l, top_r)))
            o.append('<g clip-path="url(#%s)">' % cid)
            # Everything below is clipped to the wing plate. Dividers first, then the
            # diagonal band, then three vertical stripe inlays.
            o.append(s.path(poly([(60, 624), (300, 832), (340, 1010), (60, 1010)]), fill=("#053B85", "#0C63BA")))
            diag = self.vgrad("g-wdiag", 566, 832, [(0, "#012C70"), (1, "#05468C")])
            o.append(s.path(poly([(60, 566), (300, 793), (300, 832), (60, 624)]), id="wing-band", fill=(diag, "#0868BE")))
            sa = self.vgrad("g-wsa", 700, 830, [(0, "#0364BB"), (1, "#0271C8")])
            sb = self.vgrad("g-wsb", 720, 900, [(0, "#127DD7"), (1, "#0E89E9")])
            sc = self.vgrad("g-wsc", 780, 950, [(0, "#247FD4"), (0.4, "#249CF0"), (1, "#2CA1F6")])
            o.append(s.path(poly([(60, 632), (133, 702), (133, 1010), (60, 1010)]), id="wing-stripe-a", fill=(sa, "#42B2F8")))
            o.append(s.path(poly([(152, 720), (195, 761), (195, 1010), (152, 1010)]), id="wing-stripe-b", fill=(sb, "#63C0F9")))
            o.append(s.path(poly([(214, 779), (300, 861), (340, 1010), (214, 1010)]), id="wing-stripe-c", fill=(sc, "#68C2F9")))
            o.append("</g>")
            o.append("</g>")
        o.append("</g>")
        return "\n".join(o)

    def talons(self) -> str:
        ink, w = P["ink"], self.sw(self.v.talon_ink)
        o = ['<g id="talons">']
        shapes = [(k, join(smooth(edge), [L(tr), Z()]), fills) for k, (edge, tr, fills) in enumerate(TALONS, 1)]
        for k, cmds, _ in shapes:  # all ink first so neighbouring outlines merge under the plates
            for s in self.sides:
                o.append(s.path(cmds, id="talon-ink-%d" % k, fill=ink, stroke=ink, stroke_width=w, stroke_linejoin="round"))
        for k, cmds, fills in shapes:
            for s in self.sides:
                o.append(s.path(cmds, id="talon-%d" % k, fill=fills))
        o.append("</g>")
        return "\n".join(o)

    # -- assembly -----------------------------------------------------------
    def build(self) -> str:
        parts = [self.talons(), self.body(), self.wings(), self.crown(), self.ear_tufts(), self.brow(),
                 self.eyes(), self.beak()]
        content = "\n".join(parts)
        if self.v.plate:
            content = '<rect id="plate" x="0" y="0" width="1024" height="1024" fill="%s"/>\n%s' % (self.v.plate, content)
        # Drop gradients/clips nothing references (the helpers define both sides eagerly).
        used = set(re.findall(r"url\(#([^)]+)\)", content + "\n".join(self.defs)))
        defs = [d for d in self.defs
                if not (m := re.match(r'<(?:linearGradient|clipPath) id="([^"]+)"', d)) or m.group(1) in used]
        head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" '
                'aria-labelledby="agora-owl-title">\n<title id="agora-owl-title">Agora owl</title>\n' + self.v.header)
        return "%s<defs>\n%s\n</defs>\n%s\n</svg>\n" % (head, "\n".join(defs), content)


class Side:
    """Emits geometry authored for the left half; ``i == 1`` mirrors it to the right half."""

    def __init__(self, builder: Builder, i: int):
        self.b, self.i = builder, i
        self.name = "right" if i else "left"
        self.tag = "r" if i else "l"

    def pt(self, p):
        return mir_pt(p) if self.i else p

    def cmds(self, cmds):
        return mirror_cmds(cmds) if self.i else cmds

    def path(self, cmds, id=None, fill=None, **kw):
        fill = fill[self.i] if isinstance(fill, (tuple, list)) else fill
        return self.b.path(self.cmds(cmds), id=(id + "-" + self.tag) if id else None, fill=fill, **kw)

    def ellipse(self, cx, cy, rx, ry, rot, fill=None, **kw):
        if self.i:
            cx, rot = 2 * AX - cx, -rot
        return self.b.ellipse(cx, cy, rx, ry, rot, fill=fill, **kw)

    def circle(self, cx, cy, r, **kw):
        return self.b.circle(self.pt((cx, cy))[0], cy, r, **kw)


def build_svg(variant: Variant) -> str:
    return Builder(variant).build()


# ---------------------------------------------------------------------------
# PNG export (optional dependencies) and CLI
# ---------------------------------------------------------------------------
def render_png(svg: str, size: int, dest: Path) -> None:
    try:
        import resvg_py
    except ImportError:  # pragma: no cover - dev tool
        sys.exit("PNG export needs: pip install resvg-py pillow")
    png = resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size)
    dest.write_bytes(bytes(png))


def outputs() -> dict[str, str]:
    return {"agora-logo.svg": build_svg(LOGO), "agora-favicon.svg": build_svg(FAVICON)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--png", action="store_true", help="also render agora-favicon.png and apple-touch-icon.png")
    ap.add_argument("--check", action="store_true", help="exit 1 if the SVGs on disk differ from the generator")
    ap.add_argument("--source-space", type=Path, metavar="OUT.svg",
                    help="write the full logo 1:1 with agora-logo.png pixels (for overlay comparison) and exit")
    args = ap.parse_args(argv)

    if args.source_space:
        args.source_space.write_text(build_svg(SOURCE_SPACE))
        print("wrote", args.source_space)
        return 0

    svgs = outputs()
    for name, svg in svgs.items():
        xml.dom.minidom.parseString(svg)  # fail loudly on malformed output

    if args.check:
        stale = [n for n, svg in svgs.items() if not (args.out_dir / n).exists()
                 or (args.out_dir / n).read_text() != svg]
        for n in stale:
            print("stale:", args.out_dir / n)
        return 1 if stale else 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, svg in svgs.items():
        (args.out_dir / name).write_text(svg)
        print("wrote", args.out_dir / name)
    if args.png:
        render_png(svgs["agora-favicon.svg"], 32, args.out_dir / "agora-favicon.png")
        render_png(build_svg(TOUCH), 180, args.out_dir / "apple-touch-icon.png")
        print("wrote", args.out_dir / "agora-favicon.png", args.out_dir / "apple-touch-icon.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
