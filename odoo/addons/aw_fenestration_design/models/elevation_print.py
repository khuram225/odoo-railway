# -*- coding: utf-8 -*-
"""The elevation drawing, redrawn at PRINT size.

The configurator stores the drawing it rendered (an SVG, and a PNG made from
it). Both are made at SCREEN size: the dimension labels are 10 drawing units,
and a unit is whatever the picture is later scaled to. Printed in a cell of
the Elevation Schedule (about 86 x 46 mm for a window 244 x 391 units) that is
a label of about 3 pt. The stored PNG cannot be rescaled, so the labels are
redrawn here, from the stored SVG, against the PRINTED size.

What this does, and only this: it finds the dimension lines in the stored SVG,
takes them out, and draws them again with a label of the requested size in
millimetres (so in points on the page), heavier lines and ticks, spaced so the
numbers do not touch the lines or one another, with the viewBox grown to fit.
The drawing itself (frame, panels, glyphs, hatching, badges) is the stored
one, untouched, so what is printed is what was approved on screen.

Free of Odoo imports, like layout_rules.py, so scripts/check_elevation_print.py
runs this very code on real stored drawings.

A dimension in the stored SVG is five consecutive elements, always in this
order (see the DesignConfigurator template): the dimension line, its two end
ticks (stroke rgb(74, 83, 88), width 0.8), the white knock-out
`rect` and the label `text` (a `transform` attribute, empty when horizontal,
rotate(-90 ..) when vertical). A drawing that does not match is returned
unchanged: it still prints, at its stored size.
"""
import base64
import math
import re

from lxml import etree

SVG_NS = 'http://www.w3.org/2000/svg'
PT_MM = 25.4 / 72.0                 # one point, in millimetres
# What reaches the paper. Odoo gives wkhtmltopdf `--dpi 90 --zoom 1.0667`, and the
# page then prints at 0.851 of its CSS size: a box laid out as 100 mm is 85.1 mm on
# the paper and a 12 px text is 7.7 pt, not 9. Measured on the PDFs the production
# container makes (the orange 100 mm bar and the text size in a test page, 0.8514
# and 0.8535). A "10 pt" label in CSS terms is therefore 8.5 pt on the page;
# print_for_paper() asks for the size that lands on the paper.
PAPER_SCALE = 0.851
# QtSvg draws text at a whole number of device pixels, and one pixel is 0.64 pt on
# the paper here: what prints is 5.76, 6.40, 7.04 ... 10.24 pt, and a label asked
# for 6.0 comes out 5.76. print_for_paper() asks for the next step up, so a floor
# is a floor. Read from the PDFs the production container makes.
PRINT_STEP_PT = 0.64
CHAR_EM = 0.602                     # DejaVu Sans Mono: advance per em
DIM_STROKE = 'rgb(74, 83, 88)'
DIM_COLOUR = '#4a5358'
LABEL_COLOUR = '#14181b'

# font-family the drawing is printed in. The stored value is the browser's
# whole UI stack, which the print engine cannot parse.
FONT = 'DejaVu Sans Mono, monospace'


def _q(tag):
    return '{%s}%s' % (SVG_NS, tag)


def _local(element):
    return etree.QName(element).localname


def _num(element, name, default=0.0):
    try:
        return float(re.sub(r'[a-z%]+$', '', element.get(name, '')) or default)
    except ValueError:
        return default


def _is_hair(element, vertical=None):
    """A thin dimension-coloured line (the line or a tick)."""
    if _local(element) != 'line':
        return False
    # Not `o_aw_hair`: drawings stored before that class existed have none.
    if element.get('stroke') != DIM_STROKE:
        return False
    return (element.get('stroke-width') or '').startswith('0.8')


def find_dimensions(root):
    """[(kind, [five elements], line, text)] in document order.

    kind is 'h' (the line runs left-right) or 'v'; line is (x1, y1, x2, y2).
    """
    nodes = [e for e in root.iter() if e is not root]
    found = []
    i = 0
    while i + 4 < len(nodes):
        group = nodes[i:i + 5]
        line, tick_a, tick_b, box, text = group
        if (_is_hair(line) and _is_hair(tick_a) and _is_hair(tick_b)
                and _local(box) == 'rect' and _local(text) == 'text'
                and (box.get('fill') or '').replace(' ', '') == 'rgb(255,255,255)'
                and 'transform' in text.attrib):
            x1, y1, x2, y2 = (_num(line, k) for k in ('x1', 'y1', 'x2', 'y2'))
            kind = 'h' if abs(y1 - y2) < 1e-6 else 'v'
            found.append((kind, group, (x1, y1, x2, y2),
                          (text.text or '').strip()))
            i += 5
            continue
        i += 1
    return found


def frame_box(root):
    """(x, y, w, h) of the outer frame: the largest `rect` outside <defs>."""
    best, area = None, -1.0
    for rect in root.iter(_q('rect')):
        if any(_local(a) == 'defs' for a in rect.iterancestors()):
            continue
        w, h = _num(rect, 'width'), _num(rect, 'height')
        if w * h > area:
            best, area = (_num(rect, 'x'), _num(rect, 'y'), w, h), w * h
    return best


def content_bounds(root, skip=()):
    """(minx, miny, maxx, maxy) of everything drawn except `skip`."""
    skip = set(id(e) for e in skip)
    xs, ys = [], []

    def add(x, y):
        xs.append(x)
        ys.append(y)

    for e in root.iter():
        if e is root or id(e) in skip:
            continue
        if any(_local(a) in ('defs', 'pattern') for a in e.iterancestors()):
            continue
        tag = _local(e)
        if tag == 'rect':
            x, y = _num(e, 'x'), _num(e, 'y')
            add(x, y)
            add(x + _num(e, 'width'), y + _num(e, 'height'))
        elif tag == 'line':
            add(_num(e, 'x1'), _num(e, 'y1'))
            add(_num(e, 'x2'), _num(e, 'y2'))
        elif tag in ('polyline', 'polygon'):
            nums = [float(n) for n in re.findall(
                r'-?\d+(?:\.\d+)?', e.get('points') or '')]
            for a, b in zip(nums[0::2], nums[1::2]):
                add(a, b)
        elif tag == 'circle':
            cx, cy, r = _num(e, 'cx'), _num(e, 'cy'), _num(e, 'r')
            add(cx - r, cy - r)
            add(cx + r, cy + r)
        elif tag == 'text':
            size = _num(e, 'font-size', 10.0)
            add(_num(e, 'x') - size, _num(e, 'y') - size)
            add(_num(e, 'x') + size, _num(e, 'y') + size)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


SELECTED = 'rgb(107, 74, 99)'            # the selection colour, #6b4a63
BADGE_FILL, BADGE_STROKE, BADGE_TEXT = (       # as the browser wrote the plain badge
    'rgb(255, 255, 255)', 'rgb(106, 112, 117)', 'rgb(20, 24, 27)')


def neutralise_selection(root):
    """Print every panel the same: take the editor's selection out.

    The configurator saves the drawing as it looked on screen, including
    whichever panel was selected: its number badge is purple with white text,
    a selected divider is a dashed purple line. None of that means anything
    on paper (it looks as if one panel were special), so every badge goes
    back to the plain one, and a selected divider to the plain divider. Done
    for drawings already stored (13 of the 29 first ones had a purple
    badge); the configurator no longer stores a selection in new ones.
    Returns how many things were changed.
    """
    changed = 0
    for circle in list(root.iter(_q('circle'))):
        if 'o_aw_panel_badge' not in (circle.get('class') or ''):
            continue
        if SELECTED not in (circle.get('fill'), circle.get('stroke')):
            continue
        circle.set('fill', BADGE_FILL)
        circle.set('stroke', BADGE_STROKE)
        changed += 1
        label = circle.getnext()
        if label is not None and _local(label) == 'text' and \
                'o_aw_panel_badge_text' in (label.get('class') or ''):
            label.set('fill', BADGE_TEXT)
    for group in list(root.iter()):
        classes = (group.get('class') or '').split()
        if 'o_aw_divider_selected' in classes:
            classes.remove('o_aw_divider_selected')
            group.set('class', ' '.join(classes))
            for line in group.iter(_q('line')):
                if 'o_aw_divider_line' in (line.get('class') or ''):
                    line.set('stroke-opacity', '0.55')
                    line.set('stroke-dasharray', 'none')
            changed += 1
        if 'o_aw_selection' in classes:
            group.getparent().remove(group)
            changed += 1
    return changed


def _fix_text_baselines(root, skip):
    """The print engine ignores dominant-baseline, so a text meant to be
    centred on y sits a third of an em too low. Shift it, and drop the
    attribute it cannot read."""
    skip = set(id(e) for e in skip)
    for text in root.iter(_q('text')):
        if id(text) in skip:
            continue
        mode = text.attrib.pop('dominant-baseline', None)
        if mode in ('central', 'middle'):
            size = _num(text, 'font-size', 10.0)
            text.set('y', repr(round(_num(text, 'y') + 0.35 * size, 4)))


def print_svg(svg, box_mm, label_pt, min_pt=None):
    """Redraw `svg` for a box of box_mm = (width, height) millimetres.

    Returns a dict: svg (the new text, sized in CSS px), width_mm,
    height_mm, frame_top_mm and frame_h_mm (where the window's own frame sits
    inside the image, measured from its top), label_pt (the size the labels really got: the requested size,
    or less where a label has no room in its segment), redrawn (False when
    the drawing was not recognised and is returned as stored, with its size
    only fitted to the box).
    """
    root = etree.fromstring(svg.encode('utf-8') if isinstance(svg, str) else svg)
    neutralise_selection(root)
    box_w, box_h = float(box_mm[0]), float(box_mm[1])
    vb = [float(n) for n in root.get('viewBox').split()]
    dims = find_dimensions(root)
    frame = frame_box(root)
    result = {'redrawn': False}

    if not dims or not frame:
        scale = min(box_w / vb[2], box_h / vb[3])
        _fix_text_baselines(root, ())
        _finish(root, vb, box_w, box_h, scale)
        result.update(svg=_dump(root), width_mm=vb[2] * scale,
                      height_mm=vb[3] * scale,
                      label_pt=10.0 * scale / PT_MM,
                      frame_top_mm=((frame[1] - vb[1]) * scale
                                    if frame else None),
                      frame_h_mm=frame[3] * scale if frame else None)
        return result

    old = [e for _k, group, _l, _t in dims for e in group]
    bounds = content_bounds(root, skip=old)
    fx, fy, fw, fh = frame
    horizontal = sorted({round(l[1], 2) for k, _g, l, _t in dims if k == 'h'})
    vertical = sorted({round(l[0], 2) for k, _g, l, _t in dims if k == 'v'},
                      reverse=True)

    want_mm = label_pt * PT_MM
    floor_mm = (min_pt if min_pt else label_pt) * PT_MM

    def layout(font_mm):
        """Geometry for a label font of font_mm; iterates because the
        number of drawing units per millimetre depends on the viewBox, which
        depends on the label size."""
        scale = min(box_w / vb[2], box_h / vb[3])
        for _ in range(40):
            f = font_mm / scale
            gap = 10.0
            first = 0.8 * f
            pitch = 1.5 * f
            ymax = fy + fh + gap + first + pitch * max(0, len(horizontal) - 1) + 0.7 * f
            xmin = fx - gap - first - pitch * max(0, len(vertical) - 1) - 0.7 * f
            minx = min(bounds[0], xmin)
            miny = bounds[1]
            maxx = bounds[2]
            maxy = max(bounds[3], ymax)
            # the labels' ends can stick out past the frame's edges
            for kind, _g, (x1, y1, x2, y2), text in dims:
                half = (len(text) * CHAR_EM + 0.6) * f / 2
                if kind == 'h':
                    minx = min(minx, (x1 + x2) / 2 - half, x1, x2)
                    maxx = max(maxx, (x1 + x2) / 2 + half, x1, x2)
                else:
                    miny = min(miny, (y1 + y2) / 2 - half, y1, y2)
                    maxy = max(maxy, (y1 + y2) / 2 + half, y1, y2)
            margin = 0.5 * f
            w = maxx - minx + 2 * margin
            h = maxy - miny + 2 * margin
            new_scale = min(box_w / w, box_h / h)
            if abs(new_scale - scale) < 1e-9:
                break
            scale = new_scale
        return scale, (minx - margin, miny - margin, w, h)

    def fits(font_mm, scale):
        """The largest font the segments allow at this scale."""
        limit = font_mm
        for _k, _g, (x1, y1, x2, y2), text in dims:
            length = (abs(x2 - x1) if _k == 'h' else abs(y2 - y1)) * scale
            need = len(text) * CHAR_EM + 0.9      # label box plus clearance, in em
            limit = min(limit, length / need)
        return limit

    font_mm = want_mm
    for _ in range(12):
        scale, view = layout(font_mm)
        allowed = fits(font_mm, scale)
        if allowed >= font_mm - 1e-9:
            break
        font_mm = max(allowed, 1e-3)
    if font_mm < floor_mm - 1e-9:
        # Not enough room for the floor: keep it, and the labels run close
        # to their ticks; the achieved size is reported, not hidden.
        pass
    scale, view = layout(font_mm)
    f = font_mm / scale

    # -- out with the old dimensions, in with the new ----------------------
    anchor = old[0]
    parent = anchor.getparent()
    position = parent.index(anchor)
    for element in old:
        element.getparent().remove(element)

    line_w = 0.30 / scale          # 0.30 mm printed
    tick_half = 0.45 * f
    drawn = []

    def seg(tag, **attrs):
        element = etree.Element(_q(tag))
        for k, v in attrs.items():
            element.set(k.replace('_', '-'), v if isinstance(v, str) else repr(round(v, 4)))
        drawn.append(element)
        return element

    tier_h = {y: i for i, y in enumerate(horizontal)}
    tier_v = {x: i for i, x in enumerate(vertical)}
    for kind, _g, (x1, y1, x2, y2), text in dims:
        pitch = 1.5 * f
        if kind == 'h':
            y = fy + fh + 10.0 + 0.8 * f + pitch * tier_h[round(y1, 2)]
            a, b = sorted((x1, x2))
            seg('line', x1=a, y1=y, x2=b, y2=y, stroke=DIM_COLOUR, stroke_width=line_w)
            for x in (a, b):
                seg('line', x1=x, y1=y - tick_half, x2=x, y2=y + tick_half,
                    stroke=DIM_COLOUR, stroke_width=line_w * 1.2)
            bw = (len(text) * CHAR_EM + 0.6) * f
            seg('rect', x=(a + b) / 2 - bw / 2, y=y - 0.6 * f, width=bw,
                height=1.2 * f, fill='#ffffff', stroke='none')
            t = seg('text', x=(a + b) / 2, y=y + 0.35 * f, fill=LABEL_COLOUR,
                    font_size=f, font_family=FONT, text_anchor='middle',
                    stroke='none')
            t.text = text
        else:
            x = fx - 10.0 - 0.8 * f - pitch * tier_v[round(x1, 2)]
            a, b = sorted((y1, y2))
            seg('line', x1=x, y1=a, x2=x, y2=b, stroke=DIM_COLOUR, stroke_width=line_w)
            for y in (a, b):
                seg('line', x1=x - tick_half, y1=y, x2=x + tick_half, y2=y,
                    stroke=DIM_COLOUR, stroke_width=line_w * 1.2)
            bh = (len(text) * CHAR_EM + 0.6) * f
            cy = (a + b) / 2
            seg('rect', x=x - 0.6 * f, y=cy - bh / 2, width=1.2 * f,
                height=bh, fill='#ffffff', stroke='none')
            # rotated -90 about its centre: the baseline offset is along x
            t = seg('text', x=x, y=cy + 0.35 * f, fill=LABEL_COLOUR,
                    font_size=f, font_family=FONT, text_anchor='middle',
                    stroke='none')
            t.set('transform', 'rotate(-90 %s %s)' % (repr(round(x, 4)), repr(round(cy, 4))))
            t.text = text
    for offset, element in enumerate(drawn):
        parent.insert(position + offset, element)

    _fix_text_baselines(root, drawn)
    vb_new = list(view)
    _finish(root, vb_new, box_w, box_h, scale)
    # Where the window frame is inside the image, in mm: the details beside the
    # drawing are laid out to start on its top edge and end on its bottom edge.
    result.update(svg=_dump(root), width_mm=vb_new[2] * scale,
                  height_mm=vb_new[3] * scale, label_pt=font_mm / PT_MM,
                  frame_top_mm=(fy - vb_new[1]) * scale,
                  frame_h_mm=fh * scale, redrawn=True)
    return result


CSS_PX_PER_MM = 96.0 / 25.4


def print_for_paper(svg, box_mm, paper_pt, min_paper_pt=None):
    """print_svg asked for a label size ON THE PAPER, not in CSS terms.

    box_mm is the box in CSS mm, as the template lays it out. label_pt in
    the result is the size on the paper."""
    stepped = max(1, math.ceil(paper_pt / PRINT_STEP_PT - 1e-9)) * PRINT_STEP_PT
    out = print_svg(
        svg, box_mm, stepped / PAPER_SCALE,
        min_pt=(min_paper_pt / PAPER_SCALE) if min_paper_pt else None)
    out['css_label_pt'] = out['label_pt']
    out['label_pt'] = out['label_pt'] * PAPER_SCALE
    return out


def _finish(root, vb, box_w, box_h, scale):
    root.set('viewBox', ' '.join(repr(round(v, 4)) for v in vb))
    # The drawing states its own size in CSS px (the box's size, which is also the
    # size the <img> is given in mm). Not in mm and not 100%: wkhtmltopdf draws an
    # SVG whose size is in mm at its true size inside an <img> that the page zoom
    # has made smaller (cut off, with scroll bars), and one with a percentage
    # at a default size stretched into the box (squashed). Tried both in the
    # production container; px matches the zoom.
    root.set('width', '%.2fpx' % (vb[2] * scale * CSS_PX_PER_MM))
    root.set('height', '%.2fpx' % (vb[3] * scale * CSS_PX_PER_MM))
    root.set('font-family', FONT)
    for key in ('style', 'class'):
        root.attrib.pop(key, None)


def _dump(root):
    return etree.tostring(root, encoding='unicode')


def data_uri(svg):
    """The drawing as an <img src>: wkhtmltopdf draws an SVG given this way
    (it does not reliably draw an inline <svg>)."""
    return 'data:image/svg+xml;base64,' + base64.b64encode(
        svg.encode('utf-8')).decode('ascii')
