#!/usr/bin/env python3
"""
resources/make_icon.py
Programmatically creates the MACchanger.icns icon.
Requirement: pip install Pillow
"""

import subprocess, struct, zlib, os
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


def make_icon_png(size: int) -> bytes:
    """Create an icon PNG at the requested size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = size * 0.08
    r = size * 0.22  # corner radius

    # Background
    bg_color = (18, 18, 24, 255)
    # Rounded rectangle base
    draw.rounded_rectangle([pad, pad, size - pad, size - pad],
                            radius=r, fill=bg_color)

    # Hexagon shape
    cx, cy = size / 2, size / 2
    hr = size * 0.30
    import math
    hex_pts = [(cx + hr * math.cos(math.radians(60 * i - 90)),
                cy + hr * math.sin(math.radians(60 * i - 90)))
               for i in range(6)]
    draw.polygon(hex_pts, outline=(10, 132, 255, 255), fill=(10, 132, 255, 30))

    # Inner filled hexagon
    hr2 = size * 0.18
    hex2 = [(cx + hr2 * math.cos(math.radians(60 * i - 90)),
             cy + hr2 * math.sin(math.radians(60 * i - 90)))
            for i in range(6)]
    draw.polygon(hex2, fill=(10, 132, 255, 180))

    # Center network mark: simple dot and lines
    dot_r = size * 0.05
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                 fill=(255, 255, 255, 240))
    # Connection lines
    for angle in [0, 60, 120, 180, 240, 300]:
        end_x = cx + hr2 * 0.7 * math.cos(math.radians(angle))
        end_y = cy + hr2 * 0.7 * math.sin(math.radians(angle))
        lw = max(1, size // 64)
        draw.line([cx, cy, end_x, end_y], fill=(255, 255, 255, 180), width=lw)
        sr = size * 0.03
        draw.ellipse([end_x - sr, end_y - sr, end_x + sr, end_y + sr],
                     fill=(48, 209, 88, 220))

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_icns(out_path: str):
    """
    Create a macOS .icns file.
    If Pillow is available, generate the icon programmatically; otherwise write a minimal fallback.
    """
    if not HAS_PILLOW:
        print("Pillow was not found; writing a minimal fallback icon.")
        print("Run `pip install Pillow`, then run this script again for the generated icon.")
        # Fallback: valid empty icns
        _write_minimal_icns(out_path)
        return

    import tempfile, io
    sizes = {
        "ic07": 128,
        "ic08": 256,
        "ic09": 512,
        "ic10": 1024,
        "ic11": 32,
        "ic12": 64,
        "ic13": 256,
        "ic14": 512,
    }

    # Build with iconutil
    iconset_dir = Path(out_path).with_suffix(".iconset")
    iconset_dir.mkdir(exist_ok=True)

    mapping = {
        16: "icon_16x16.png",
        32: ("icon_16x16@2x.png", "icon_32x32.png"),
        64: "icon_32x32@2x.png",
        128: "icon_128x128.png",
        256: ("icon_128x128@2x.png", "icon_256x256.png"),
        512: ("icon_256x256@2x.png", "icon_512x512.png"),
        1024: "icon_512x512@2x.png",
    }

    for sz, names in mapping.items():
        png_data = make_icon_png(sz)
        if isinstance(names, str):
            names = (names,)
        for name in names:
            (iconset_dir / name).write_bytes(png_data)

    r = subprocess.run(["iconutil", "-c", "icns", str(iconset_dir),
                        "-o", out_path], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"Icon created: {out_path}")
    else:
        print(f"iconutil error: {r.stderr}")
        _write_minimal_icns(out_path)

    # Clean up
    import shutil
    shutil.rmtree(iconset_dir, ignore_errors=True)


def _write_minimal_icns(out_path: str):
    """Write a valid but empty .icns fallback file."""
    # ICNS header: magic + length (8 bytes header only)
    data = b"icns" + struct.pack(">I", 8)
    Path(out_path).write_bytes(data)
    print(f"Minimal icns written: {out_path}")


if __name__ == "__main__":
    out = Path(__file__).parent / "MACchanger.icns"
    build_icns(str(out))
