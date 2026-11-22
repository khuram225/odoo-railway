#!/usr/bin/env python3
"""Runs the REAL watermark_image.watermark (Odoo-free): the logo comes out faded to
15% (in the image, not by CSS: wkhtmltopdf would bitmap a CSS-translucent element and
soften the text around it), turned 35 degrees counter-clockwise, and never bigger than
its page; a logo that is not an image gives nothing, not an error."""
import importlib.util
import io
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print('watermark: SKIP, Pillow is not installed')
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    'aw_watermark_image',
    ROOT / 'odoo' / 'addons' / 'aw_fenestration_design' / 'models' / 'watermark_image.py')
wi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wi)

failures = []


def check(name, ok, detail=''):
    if not ok:
        failures.append('%s %s' % (name, detail))


def png(image):
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


# a wide logo: a bar across the middle, opaque, on a transparent ground
logo = Image.new('RGBA', (1182, 591), (0, 0, 0, 0))
ImageDraw.Draw(logo).rectangle((0, 270, 1181, 320), fill=(30, 50, 140, 255))
for page in ((330.0, 228.0), (223.0, 300.0)):
    result = wi.watermark(png(logo), *page)
    check('page %s: made' % (page,), result is not None)
    data, w_mm, h_mm = result
    out = Image.open(io.BytesIO(data))
    check('RGBA out', out.mode == 'RGBA', out.mode)
    top = out.getchannel('A').getextrema()[1]
    check('faded to 15%% (alpha at most %d)' % round(255 * wi.OPACITY), 0 < top <= round(255 * wi.OPACITY) + 1, top)
    check('never bigger than the page', w_mm <= page[0] * wi.FIT + 0.01 and h_mm <= page[1] * wi.FIT + 0.01,
          (w_mm, h_mm))
    check('keeps the picture\'s proportions', abs(w_mm / h_mm - out.width / out.height) < 0.01)
    # turned counter-clockwise: the bar's right end is higher (smaller y) than its left
    alpha = out.getchannel('A')
    px = alpha.load()
    left, right = [], []
    for y in range(out.height):
        for x in range(out.width):
            if px[x, y] > 5:
                (left if x < out.width / 2 else right).append(y)
    check('turned counter-clockwise',
          sum(right) / len(right) < sum(left) / len(left) - 20,
          (sum(left) / len(left), sum(right) / len(right)))
    check('a few KB, not a bitmap of the page', len(data) < 200 * 1024, len(data))

# on a wide page the unturned logo is 70% of the page's width
data, w_mm, h_mm = wi.watermark(png(logo), 600.0, 600.0)
turned_ratio = Image.open(io.BytesIO(data)).width / float(wi.MAX_PX)
check('unturned logo is 70%% of the width', abs(w_mm / turned_ratio - 0.7 * 600.0) < 1.0, w_mm / turned_ratio)

# an opaque JPEG-like logo (no alpha) is faded too
flat = Image.new('RGB', (400, 200), (200, 0, 0))
buf = io.BytesIO()
flat.save(buf, 'JPEG')
result = wi.watermark(buf.getvalue(), 330.0, 228.0)
check('a JPEG logo works', result is not None)
check('and is faded', Image.open(io.BytesIO(result[0])).getchannel('A').getextrema()[1] <= round(255 * wi.OPACITY) + 1)

# not an image: nothing, no error
check('bytes that are not an image', wi.watermark(b'not an image', 330.0, 228.0) is None)
check('empty', wi.watermark(b'', 330.0, 228.0) is None)

if failures:
    print('watermark: %d problem(s)' % len(failures))
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('watermark: faded to 15%, turned, fits the page, a bad logo gives nothing')
