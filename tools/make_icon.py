#!/usr/bin/env python3
"""Render the brand icons: a flat, generic broadband gateway (box, LEDs, LAN ports, signal arcs).
Deliberately not any carrier's logo. Writes brand/*.png and assets/icon.svg. Needs Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "custom_components/att_bgw/brand"
BOX = 512
TOP, BOTTOM = (0x2F, 0x9B, 0xFF), (0x0B, 0x4F, 0xC4)  # body gradient
ARC, LED_ON, LED_DIM, PORT = (0x2F, 0x9B, 0xFF), (0x3D, 0xF5, 0x8C), (0x9F, 0xD8, 0xFF), (0x06, 0x2A, 0x6E)

BODY = (56, 250, 456, 440, 56)  # x0, y0, x1, y1, corner radius
ARCS = [(256, 250, r, w) for r, w in ((70, 26), (140, 26), (210, 26))]  # centre x, y, radius, width
LEDS = [(126 + i * 52, 300, 14) for i in range(4)]
PORTS = [(112 + i * 76, 352, 56, 44) for i in range(4)]  # x, y, w, h


def render(size: int) -> Image.Image:
    ss = 4
    s = size * ss / BOX
    img = Image.new("RGBA", (size * ss,) * 2, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for cx, cy, r, w in ARCS:  # upper half-circle arcs, fading outward
        d.arc([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s], 205, 335, fill=ARC, width=round(w * s))
    x0, y0, x1, y1, rad = BODY
    grad = Image.new("RGBA", img.size)
    g = ImageDraw.Draw(grad)
    for y in range(img.size[1]):
        f = min(max((y / s - y0) / (y1 - y0), 0), 1)
        g.line([(0, y), (img.size[0], y)], fill=tuple(round(a + (b - a) * f) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([x0 * s, y0 * s, x1 * s, y1 * s], radius=rad * s, fill=255)
    img.paste(grad, (0, 0), mask)
    for i, (cx, cy, r) in enumerate(LEDS):
        d.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s], fill=LED_ON if i < 3 else LED_DIM)
    for x, y, w, h in PORTS:
        d.rounded_rectangle([x * s, y * s, (x + w) * s, (y + h) * s], radius=8 * s, fill=PORT)
    return img.resize((size, size), Image.LANCZOS)


def svg() -> str:
    hexc = lambda c: "#%02x%02x%02x" % c
    x0, y0, x1, y1, rad = BODY
    parts = [f'<defs><linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{hexc(TOP)}"/>'
             f'<stop offset="1" stop-color="{hexc(BOTTOM)}"/></linearGradient></defs>']
    import math
    for cx, cy, r, w in ARCS:
        a0, a1 = math.radians(205), math.radians(335)
        sx, sy, ex, ey = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
        parts.append(f'<path d="M{sx:.1f} {sy:.1f} A{r} {r} 0 0 1 {ex:.1f} {ey:.1f}" fill="none" '
                     f'stroke="{hexc(ARC)}" stroke-width="{w}"/>')
    parts.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="{rad}" fill="url(#b)"/>')
    for i, (cx, cy, r) in enumerate(LEDS):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{hexc(LED_ON if i < 3 else LED_DIM)}"/>')
    for x, y, w, h in PORTS:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{hexc(PORT)}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX} {BOX}">{"".join(parts)}</svg>\n'


def main() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets/icon.svg").write_text(svg())
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        render(size).save(BRAND / name)
    print("wrote", sorted(p.name for p in BRAND.iterdir()), "+ assets/icon.svg")


if __name__ == "__main__":
    main()
