"""Generates the Sahifa logo assets.

The mark is a sheet (a ṣaḥīfa) with a folded corner and three ruled lines, the rows of a
table, sealed at the lower right with a round seal carrying an eight-pointed star: a record
whose promises are written down and checked. Hand-tuned geometry on a 400×400 grid.

The wordmark is outlined into SVG paths, so it looks the same in every renderer (GitHub
shows SVGs without web fonts): "Sahifa" in Bricolage Grotesque Bold, "صحيفة" in Noto Kufi
Arabic Bold shaped with HarfBuzz, the tagline in Figtree Medium. All three fonts are under
the SIL Open Font Licence and are fetched from the Fontsource packages on jsDelivr into
~/.cache/sahifa-fonts on the first run. Run from the repository root:

    uv run --with fonttools --with uharfbuzz python docs/assets/genlogo.py
    uv run --with fonttools --with uharfbuzz python docs/assets/genlogo.py --no-png

Writes into docs/assets/, web/public/ and site/assets/. PNGs (social preview, touch and
manifest icons) are rendered with headless Chromium: set SAHIFA_CHROMIUM to the binary, or
have Playwright's Chromium (PLAYWRIGHT_BROWSERS_PATH or ~/.cache/ms-playwright), or
`chromium` / `google-chrome` on PATH. Without one the PNG step is skipped with a notice.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

INK = "#141b2d"
PAPER = "#fbfcfd"
LAPIS = "#2b4fb3"
INK_DARK = "#e8ecf4"  # strokes on dark backgrounds
PAPER_DARK = "#151c2e"
LAPIS_DARK = "#93abff"
BG_DARK = "#0d1220"
MUTED = "#4a5569"
MUTED_DARK = "#a6b0c5"

ASSETS = Path(__file__).resolve().parent
ROOT = ASSETS.parent.parent
TARGETS = [ROOT / "web" / "public", ROOT / "site" / "assets"]
FONT_CACHE = Path.home() / ".cache" / "sahifa-fonts"
FONTSOURCE = "https://cdn.jsdelivr.net/npm/@fontsource"
FONTS = {
    "latin": "bricolage-grotesque/files/bricolage-grotesque-latin-700-normal.woff",
    "arabic": "noto-kufi-arabic/files/noto-kufi-arabic-arabic-700-normal.woff",
    "text": "figtree/files/figtree-latin-500-normal.woff",
}

# Geometry on the 400 grid.
SHEET = "M96 48 H252 L320 116 V336 Q320 352 304 352 H96 Q80 352 80 336 V64 Q80 48 96 48 Z"
FOLD = "M252 48 V100 Q252 116 268 116 H320"
# Each ruled line is a record: a short key cell and a value cell.
ROWS = [
    ((132, 168), (156, 168)), ((190, 168), (268, 168)),
    ((132, 220), (156, 220)), ((190, 220), (248, 220)),
    ((132, 272), (156, 272)), ((190, 272), (200, 272)),
]
SEAL = (292, 300, 76)  # centre x, centre y, radius
STAR_R = 46  # outer radius of the star; solid, so it reads as a seal and not a gear

PNG_JOBS = [
    ("social-preview.svg", ASSETS / "social-preview.png", 1280, 640),
    ("icon.svg", ROOT / "web" / "public" / "icon-180.png", 180, 180),
    ("icon.svg", ROOT / "web" / "public" / "icon-192.png", 192, 192),
    ("icon.svg", ROOT / "web" / "public" / "icon-512.png", 512, 512),
]


def star(cx: float, cy: float, r: float) -> str:
    """The eight-pointed star of two overlapping squares (Rub el Hizb), as one solid shape."""
    inner = r * math.cos(math.radians(45)) / math.cos(math.radians(22.5))
    pts = []
    for k in range(16):
        rad = r if k % 2 == 0 else inner
        a = math.radians(-90 + k * 22.5)
        pts.append(f"{cx + rad * math.cos(a):.2f} {cy + rad * math.sin(a):.2f}")
    return "M" + " L".join(pts) + " Z"


def mark(x: float = 0, y: float = 0, scale: float = 1.0, *, ink: str, paper: str, seal: str,
         stroke: float = 22) -> str:
    cx, cy, r = SEAL
    rows = "".join(
        f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}"/>' for a, b in ROWS
    )
    return (
        f'<g transform="translate({x},{y}) scale({scale})">'
        f'<path d="{SHEET}" fill="{paper}" stroke="{ink}" stroke-width="{stroke}" stroke-linejoin="round"/>'
        f'<path d="{FOLD}" fill="none" stroke="{ink}" stroke-width="{stroke}" stroke-linejoin="round"/>'
        f'<g stroke="{ink}" stroke-width="{stroke}" stroke-linecap="round">{rows}</g>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{seal}" stroke="{paper}" stroke-width="14"/>'
        f'<path d="{star(cx, cy, STAR_R)}" fill="{paper}" stroke="{paper}" stroke-width="4" '
        f'stroke-linejoin="round"/>'
        "</g>"
    )


def svg(width: int, height: int, body: str, *, background: str | None = None, rx: int = 0) -> str:
    bg = f'<rect width="{width}" height="{height}" rx="{rx}" fill="{background}"/>' if background else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-label="Sahifa">\n<title>Sahifa</title>\n{bg}\n{body}\n</svg>\n'
    )


# --- outlined text -------------------------------------------------------------------------


def font_path(key: str) -> Path:
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    target = FONT_CACHE / Path(FONTS[key]).name
    if not target.exists():
        url = f"{FONTSOURCE}/{FONTS[key]}"
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed https URL
            target.write_bytes(resp.read())
    return target


def text_path(text: str, key: str, x: float, baseline: float, size: float, *, rtl: bool = False,
              tracking: float = 0.0) -> tuple[str, float]:
    """Shape `text` with HarfBuzz and return (SVG path data, advance width) at `size` px."""
    import uharfbuzz as hb
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    path = font_path(key)
    tt = TTFont(str(path))
    upem = tt["head"].unitsPerEm
    # HarfBuzz reads the sfnt data; WOFF is decompressed by fontTools first.
    with tempfile.NamedTemporaryFile(suffix=".ttf") as tmp:
        tt.flavor = None
        tt.save(tmp.name)
        face = hb.Face(Path(tmp.name).read_bytes())
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    if rtl:
        buf.direction = "rtl"
    hb.shape(font, buf, {"kern": True, "liga": True})
    glyph_set = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    scale = size / upem
    pen = SVGPathPen(glyph_set)
    cursor = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
        name = order[info.codepoint]
        gx = x + (cursor + pos.x_offset) * scale
        gy = baseline - pos.y_offset * scale
        glyph_set[name].draw(TransformPen(pen, (scale, 0, 0, -scale, gx, gy)))
        cursor += pos.x_advance + tracking * upem / size
    return pen.getCommands(), cursor * scale


def word(text: str, key: str, x: float, baseline: float, size: float, colour: str, **kw: object) -> tuple[str, float]:
    d, width = text_path(text, key, x, baseline, size, **kw)  # type: ignore[arg-type]
    return f'<path d="{d}" fill="{colour}"/>', width


# --- assets --------------------------------------------------------------------------------


def lockup(ink: str, paper: str, seal: str, muted: str) -> str:
    latin, w = word("Sahifa", "latin", 236, 136, 120, ink, tracking=-2.4)
    arabic, _ = word("صحيفة", "arabic", 236 + w + 30, 132, 64, muted, rtl=True)
    return mark(0, 0, 0.5, ink=ink, paper=paper, seal=seal) + latin + arabic


def build_svgs() -> dict[str, str]:
    files: dict[str, str] = {}
    files["mark.svg"] = svg(400, 400, mark(ink=INK, paper=PAPER, seal=LAPIS))
    files["mark-dark.svg"] = svg(400, 400, mark(ink=INK_DARK, paper=PAPER_DARK, seal=LAPIS_DARK))
    # Icon: the mark on an ink tile; heavier strokes so it reads at 16 px.
    files["icon.svg"] = svg(400, 400, mark(30, 26, 0.86, ink=INK, paper=PAPER, seal=LAPIS, stroke=26),
                            background=INK, rx=88)
    files["logo-light.svg"] = svg(860, 200, lockup(INK, PAPER, LAPIS, MUTED))
    files["logo-dark.svg"] = svg(860, 200, lockup(INK_DARK, PAPER_DARK, LAPIS_DARK, MUTED_DARK))

    arabic, _ = word("صحيفة", "arabic", 566, 182, 60, MUTED_DARK, rtl=True)
    latin, _ = word("Sahifa", "latin", 560, 300, 150, INK_DARK, tracking=-3)
    tag, _ = word("Know what your data promises,", "text", 566, 382, 44, INK_DARK)
    tag2, _ = word("and whether it keeps it.", "text", 566, 436, 44, INK_DARK)
    sub, _ = word("Self-hosted data quality for whole data stores", "text", 566, 506, 28, MUTED_DARK)
    body = mark(110, 128, 0.96, ink=INK_DARK, paper=PAPER_DARK, seal=LAPIS_DARK) + latin + arabic + tag + tag2 + sub
    files["social-preview.svg"] = svg(1280, 640, body, background=BG_DARK)

    for name, content in files.items():
        (ASSETS / name).write_text(content)
    for target in TARGETS:
        if target.is_dir():
            shutil.copy(ASSETS / "icon.svg", target / "favicon.svg")
            shutil.copy(ASSETS / "mark.svg", target / "logo.svg")
    print("wrote", ", ".join(files))  # noqa: T201 - script output
    return files


def find_chromium() -> str | None:
    env = os.environ.get("SAHIFA_CHROMIUM")
    if env and Path(env).is_file():
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for cache in (os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), str(Path.home() / ".cache" / "ms-playwright")):
        if not cache or not Path(cache).is_dir():
            continue
        for candidate in sorted(Path(cache).glob("chromium-*/chrome-linux*/chrome"), reverse=True):
            return str(candidate)
    return None


def build_pngs() -> None:
    chromium = find_chromium()
    if not chromium:
        print("no Chromium found; PNGs not rendered (set SAHIFA_CHROMIUM)")  # noqa: T201
        return
    with tempfile.TemporaryDirectory() as tmp:
        for source, out, width, height in PNG_JOBS:
            if not out.parent.is_dir():
                continue
            page = Path(tmp) / "page.html"
            page.write_text(
                f"<!doctype html><html><body style='margin:0;background:transparent'>"
                f"<img src='{(ASSETS / source).as_uri()}' width='{width}' height='{height}'></body></html>"
            )
            subprocess.run(  # noqa: S603 - fixed argument list
                [chromium, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                 "--default-background-color=00000000", f"--window-size={width},{height}",
                 f"--screenshot={out}", page.as_uri()],
                check=True, capture_output=True, timeout=60,
            )
            print("rendered", out.relative_to(ROOT))  # noqa: T201


if __name__ == "__main__":
    build_svgs()
    if "--no-png" not in sys.argv:
        build_pngs()
