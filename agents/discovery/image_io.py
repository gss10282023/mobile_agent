# -*- coding: utf-8 -*-
# image_io.py
from __future__ import annotations

from typing import List, Optional, Tuple
from pathlib import Path
from PIL import Image
import io
import base64


def decode_b64_to_image(b64_png: str) -> Optional[Image.Image]:
    """Decode base64 PNG to PIL.Image; return None on failure."""
    try:
        return Image.open(io.BytesIO(base64.b64decode(b64_png)))
    except Exception:
        return None


def save_b64_png_to_file(b64_png: str, path: Path) -> bool:
    """Decode base64 PNG and save to file path; return True on success."""
    try:
        img = Image.open(io.BytesIO(base64.b64decode(b64_png)))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(path), format="PNG")
        return True
    except Exception:
        return False


def resize_image(img: Image.Image, max_w: int) -> Image.Image:
    """Resize image to <= max_w while preserving aspect ratio."""
    if img.width <= max_w:
        return img
    new_h = int(img.height * (max_w / img.width))
    return img.resize((max_w, new_h), Image.LANCZOS)


def resize_b64_png(b64_png: str, max_w: int) -> str:
    """Resize a base64 PNG to max_w; return original b64 if decode fails."""
    img = decode_b64_to_image(b64_png)
    if img is None:
        return b64_png
    img = resize_image(img, max_w)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def stitch_vertical(
    images: List[Image.Image],
    margin: int = 8,
    bg: Tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Stitch images vertically with margin; raise if empty."""
    if not images:
        raise ValueError("No images to stitch")
    widths = [im.width for im in images]
    heights = [im.height for im in images]
    max_w = max(widths)
    total_h = sum(heights) + (len(images) - 1) * margin
    canvas = Image.new("RGB", (max_w, total_h), bg)
    y = 0
    for i, im in enumerate(images):
        canvas.paste(im, (0, y))
        y += im.height
        if i < len(images) - 1:
            y += margin
    return canvas
