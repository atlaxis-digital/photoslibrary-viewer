"""Render the app icons (run once; output is committed)."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).parent.parent / "photoslibrary_viewer" / "static" / "icons"
BG, TILE, SUN, MOUNTAIN = "#1d1d22", "#eef0f5", "#f2a93b", "#3d6fd9"


def draw(size: int, maskable: bool) -> Image.Image:
    s = 4  # supersample
    n = size * s
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if maskable:
        d.rectangle((0, 0, n, n), fill=TILE)
        pad = n * 0.2  # keep motif inside the 80 % safe zone
    else:
        d.rounded_rectangle((0, 0, n - 1, n - 1), radius=n * 0.22, fill=TILE)
        pad = n * 0.1
    box = n - 2 * pad
    u = box / 32  # motif drawn on a 32-unit grid, like the favicon
    def p(x, y):
        return (pad + x * u, pad + y * u)
    cx, cy, r = 12, 12, 4
    d.ellipse((*p(cx - r, cy - r), *p(cx + r, cy + r)), fill=SUN)
    d.polygon([p(4, 26), p(12, 17), p(17, 22), p(21, 18), p(28, 26)], fill=MOUNTAIN)
    return im.resize((size, size), Image.Resampling.LANCZOS)


for size in (192, 512):
    draw(size, False).save(OUT / f"icon-{size}.png", optimize=True)
    draw(size, True).save(OUT / f"maskable-{size}.png", optimize=True)
draw(180, True).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
