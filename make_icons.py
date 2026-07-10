#!/usr/bin/env python3
"""Generate PWA icons for the training dashboard (run once, or after a rebrand)."""

from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "docs" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG = (20, 26, 25, 255)       # --bg dark
TRAINING = (204, 112, 56, 255)   # --training dark-mode accent
RECOVERY = (31, 158, 150, 255)   # --recovery dark-mode accent


def draw_mark(size, margin_ratio):
    """Three ascending bars (training) with a recovery-colored dot -- echoes the
    dashboard's own volume chart + accent dot motif."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    corner = int(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=corner, fill=BG)

    margin = size * margin_ratio
    content = size - 2 * margin
    bar_w = content * 0.16
    gap = content * 0.12
    base_y = size - margin - content * 0.12

    heights = [0.38, 0.62, 0.9]
    x = margin
    for h in heights:
        bar_h = content * h
        draw.rounded_rectangle(
            [x, base_y - bar_h, x + bar_w, base_y],
            radius=bar_w * 0.25,
            fill=TRAINING,
        )
        x += bar_w + gap

    dot_r = content * 0.09
    dot_cx = margin + content - dot_r * 0.4
    dot_cy = margin + content * 0.12
    draw.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=RECOVERY)

    return img


for size in (192, 512):
    draw_mark(size, margin_ratio=0.16).save(OUT / f"icon-{size}.png")
    draw_mark(size, margin_ratio=0.30).save(OUT / f"icon-{size}-maskable.png")

print(f"Wrote icons to {OUT}")
