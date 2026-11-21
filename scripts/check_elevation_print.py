#!/usr/bin/env python3
"""The elevation drawing is redrawn at print size, or this fails.

Runs the REAL `print_svg` (aw_fenestration_design/models/elevation_print.py,
Odoo-free for exactly this) on four drawings the configurator really stored
(tests/data/elevation_*.svg: two casements, three panels, a tall narrow one,
and one from before the `o_aw_hair` class existed) and checks what a printed
page needs:

  * every dimension in the stored drawing is found and redrawn;
  * the dimension labels are at least 10 pt on the page for the one-window
    sheet and at least 5 pt in the six-per-page schedule (the size is read
    back from the OUTPUT, not trusted from the return value), where they were
    3.3 pt;
  * no label box touches another, a tick, or another dimension's line;
  * everything is inside the viewBox and the drawing fits its box;
  * the drawing itself (frame, panels, glyphs) is the stored one, untouched;
  * a drawing it does not recognise comes back as stored, never an error.
"""
import importlib.util
import re
import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / 'odoo' / 'addons' / 'aw_fenestration_design'
spec = importlib.util.spec_from_file_location(
    'aw_elevation_print', ADDON / 'models' / 'elevation_print.py')
ep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ep)

SHEET = ((168.0, 150.0), 10.0, 10.0)        # box mm, label pt, floor pt
SCHEDULE = ((86.0, 46.0), 6.0, 5.0)

failures = []


def check(label, ok, detail=''):
    if not ok:
        failures.append('%s %s' % (label, detail))


def num(e, k):
    return float(re.sub(r'[a-z%]+$', '', e.get(k, '0')) or 0)


def boxes_overlap(a, b, pad=1e-6):
    return not (a[2] <= b[0] + pad or b[2] <= a[0] + pad
                or a[3] <= b[1] + pad or b[3] <= a[1] + pad)


def segment_hits_box(seg, box):
    x1, y1, x2, y2 = seg
    return boxes_overlap((min(x1, x2) - 1e-9, min(y1, y2) - 1e-9,
                          max(x1, x2) + 1e-9, max(y1, y2) + 1e-9), box)


files = sorted((ADDON / 'tests' / 'data').glob('elevation_*.svg'))
check('fixtures present', len(files) >= 4, [f.name for f in files])

for path in files:
    svg = path.read_text(encoding='utf-8')
    before = etree.fromstring(svg.encode())
    stored_dims = ep.find_dimensions(before)
    check('%s: dimensions found' % path.name, len(stored_dims) >= 3, len(stored_dims))

    for (box, pt, floor), kind in ((SHEET, 'sheet'), (SCHEDULE, 'schedule')):
        tag = '%s/%s' % (path.name, kind)
        out = ep.print_svg(svg, box, pt, min_pt=floor)
        check(tag + ': redrawn', out['redrawn'])
        root = etree.fromstring(out['svg'].encode())          # well-formed XML
        vb = [float(n) for n in root.get('viewBox').split()]
        width_mm, height_mm = num(root, 'width'), num(root, 'height')
        check(tag + ': width and height are in mm',
              root.get('width', '').endswith('mm') and root.get('height', '').endswith('mm'))
        check(tag + ': fits its box',
              width_mm <= box[0] + 0.01 and height_mm <= box[1] + 0.01,
              (width_mm, height_mm))
        scale = width_mm / vb[2]
        check(tag + ': one scale in both directions',
              abs(height_mm / vb[3] - scale) < 1e-3 * scale)   # sizes are written to 0.001 mm

        # -- the label size, read back from the output -------------------
        texts = [t for t in root.iter(ep._q('text'))
                 if t.get('fill') == ep.LABEL_COLOUR]
        check(tag + ': one label per dimension', len(texts) == len(stored_dims),
              (len(texts), len(stored_dims)))
        for t in texts:
            size_pt = num(t, 'font-size') * scale / ep.PT_MM
            check(tag + ': label %s is at least %.1f pt' % (t.text, floor),
                  size_pt >= floor - 0.05, round(size_pt, 2))
        reported = out['label_pt']
        check(tag + ': the reported size is the drawn size',
              all(abs(num(t, 'font-size') * scale / ep.PT_MM - reported) < 0.05
                  for t in texts), reported)
        if kind == 'sheet':
            check(tag + ': 10 pt on the sheet', reported >= 10.0 - 0.05, reported)

        # -- nothing touches ---------------------------------------------
        label_boxes = []
        for r in root.iter(ep._q('rect')):
            if r.get('fill') == '#ffffff' and r.get('stroke') == 'none':
                label_boxes.append((num(r, 'x'), num(r, 'y'),
                                    num(r, 'x') + num(r, 'width'),
                                    num(r, 'y') + num(r, 'height')))
        check(tag + ': a box per label', len(label_boxes) == len(texts),
              (len(label_boxes), len(texts)))
        for i, a in enumerate(label_boxes):
            for b in label_boxes[i + 1:]:
                check(tag + ': two label boxes overlap', not boxes_overlap(a, b), (a, b))
        dim_lines = [(num(l, 'x1'), num(l, 'y1'), num(l, 'x2'), num(l, 'y2'),
                      num(l, 'stroke-width'))
                     for l in root.iter(ep._q('line'))
                     if l.get('stroke') == ep.DIM_COLOUR]
        for box_ in label_boxes:
            hits = [s for s in dim_lines if segment_hits_box(s[:4], box_)]
            # exactly its own dimension line passes behind it; no tick, no other line
            check(tag + ': a label box meets only its own line', len(hits) == 1, len(hits))
        line_mm = min(s[4] for s in dim_lines) * scale     # the ticks are 1.2 x heavier
        check(tag + ': dimension lines are 0.3 mm (were 0.1)', abs(line_mm - 0.30) < 0.02, line_mm)

        # -- everything inside the viewBox -------------------------------
        xs, ys = [], []
        for b in label_boxes:
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        for s in dim_lines:
            xs += [s[0], s[2]]
            ys += [s[1], s[3]]
        check(tag + ': inside the viewBox',
              min(xs) >= vb[0] - 1e-6 and max(xs) <= vb[0] + vb[2] + 1e-6
              and min(ys) >= vb[1] - 1e-6 and max(ys) <= vb[1] + vb[3] + 1e-6,
              (vb, min(xs), max(xs), min(ys), max(ys)))

        # -- the drawing itself is the stored one -------------------------
        def geometry(tree, skip):
            skip_ids = set(id(e) for e in skip)
            out = []
            for e in tree.iter():
                if e is tree or id(e) in skip_ids:
                    continue
                name = etree.QName(e).localname
                if name in ('rect', 'polyline', 'circle', 'path', 'polygon'):
                    out.append((name, e.get('x'), e.get('y'), e.get('width'),
                                e.get('height'), e.get('points'), e.get('cx'),
                                e.get('cy'), e.get('d'), e.get('fill')))
            return sorted(out, key=repr)

        old = [e for _k, g, _l, _t in stored_dims for e in g]
        kept_before = geometry(before, old)
        new_boxes = [r for r in root.iter(ep._q('rect'))
                     if r.get('fill') == '#ffffff' and r.get('stroke') == 'none']
        kept_after = geometry(root, new_boxes)
        check(tag + ': the stored drawing is untouched', kept_before == kept_after,
              (len(kept_before), len(kept_after)))

    # -- the old size, for the record ------------------------------------
    vb = [float(n) for n in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    old_pt = 10 * min(86.0 / vb[2], 46.0 / vb[3]) / ep.PT_MM
    check('%s: it was small in the schedule' % path.name, old_pt < 4.0, old_pt)

# -- a drawing it does not recognise ----------------------------------------
plain = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
         '<rect x="10" y="10" width="180" height="80" fill="none" stroke="#000"/></svg>')
out = ep.print_svg(plain, (86.0, 46.0), 6.0)
check('unrecognised drawing is returned, not an error', out['redrawn'] is False)
check('and is still fitted to its box',
      abs(out['width_mm'] - 86.0) < 0.01 or abs(out['height_mm'] - 43.0) < 0.5, out['width_mm'])
check('data uri', ep.data_uri(plain).startswith('data:image/svg+xml;base64,'))

if failures:
    print("FAIL: %d problem(s)" % len(failures))
    for line in failures[:40]:
        print("  -", line)
    sys.exit(1)
print("elevation print: %d drawings redrawn at print size, every check holds"
      % len(files))
