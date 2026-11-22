# -*- coding: utf-8 -*-
"""The company logo as a watermark image (Odoo-free: `scripts/check_watermark.py`).

The fade and the turn are made HERE, in the image, and not with CSS `opacity` and
`transform`: wkhtmltopdf draws a transformed or translucent element by rendering it
into a bitmap, and a bitmap in the middle of a page of text is how a print comes out
soft. A PNG whose alpha is already 15% and which is already turned prints as one plain
image, and the text over it stays text.
"""
import io

ANGLE = -35.0        # degrees, as CSS writes it: negative turns counter-clockwise
OPACITY = 0.15
WIDTH_FRACTION = 0.70   # of the page's width, the logo itself (before it is turned)
MAX_PX = 900            # the logo's own width in the file; it prints at ~170 mm
FIT = 0.97              # the turned image never takes more than this of the page


def watermark(logo_bytes, page_w_mm, page_h_mm, angle=ANGLE, opacity=OPACITY,
              width_fraction=WIDTH_FRACTION):
    """(png bytes, width_mm, height_mm) of the turned, faded logo for a page of
    `page_w_mm` x `page_h_mm`, or None when the bytes are not an image.
    The logo is `width_fraction` of the page's width before it is turned, and is
    made smaller if the turned image would not fit the page."""
    from PIL import Image
    try:
        image = Image.open(io.BytesIO(logo_bytes))
        image.load()
    except Exception:
        return None
    image = image.convert('RGBA')
    if image.width > MAX_PX:
        image = image.resize(
            (MAX_PX, max(1, round(image.height * MAX_PX / image.width))),
            Image.LANCZOS)
    alpha = image.getchannel('A').point(lambda v: int(round(v * opacity)))
    image.putalpha(alpha)
    # PIL turns counter-clockwise for a positive angle; CSS' negative is the same turn
    turned = image.rotate(-angle, expand=True, resample=Image.BICUBIC)
    # bicubic overshoots at a sharp edge: never above the opacity asked for
    cap = int(round(255 * opacity))
    turned.putalpha(turned.getchannel('A').point(lambda v: min(v, cap)))
    # mm per pixel so the UNTURNED logo is width_fraction of the page's width
    mm_per_px = page_w_mm * width_fraction / image.width
    w_mm, h_mm = turned.width * mm_per_px, turned.height * mm_per_px
    shrink = min(1.0, FIT * page_w_mm / w_mm, FIT * page_h_mm / h_mm)
    out = io.BytesIO()
    turned.save(out, format='PNG', optimize=True)
    return out.getvalue(), w_mm * shrink, h_mm * shrink
