# -*- coding: utf-8 -*-
"""Tell a drawing that was COPIED from a source window from one a window drew itself
(Odoo-free, `scripts/check_drawing_mark.py` runs the real functions).

A copy made by Make copies or Duplicate position takes its source's stored drawing, so
it prints a picture without being opened. If somebody then changes the copy's size in
the form, that picture is the source's, at the source's size. To say so on the print
without a new column, the copy's SVG carries two attributes on its root element: the
source's Design Ref and its size. The configurator stores a brand-new SVG when the
window is opened and saved, which has neither, so the mark goes by itself.
"""
import re

_ROOT = re.compile(r'<svg\b')
_MARK = re.compile(
    r'<svg\b[^>]*?\sdata-aw-from="([^"]*)"[^>]*?\sdata-aw-size="([^"]*)"')


def size_text(width_mm, height_mm):
    return '%.1fx%.1f' % (width_mm or 0.0, height_mm or 0.0)


def _attr(text):
    return (str(text or '').replace('&', '&amp;').replace('"', '&quot;')
            .replace('<', '&lt;').replace('>', '&gt;'))


def mark(svg, ref, size):
    """The SVG with the source's ref and size on its root element; an SVG that
    already carries a mark (a copy of a copy) is returned as it is, so the mark
    always names the window the picture really came from."""
    if not svg or read_mark(svg):
        return svg
    return _ROOT.sub(
        '<svg data-aw-from="%s" data-aw-size="%s"' % (_attr(ref), _attr(size)),
        svg, count=1)


def read_mark(svg):
    """(source ref, size text) of a copied drawing, or None."""
    found = _MARK.search(svg or '')
    if not found:
        return None
    ref, size = found.group(1), found.group(2)
    return (ref.replace('&quot;', '"').replace('&lt;', '<')
            .replace('&gt;', '>').replace('&amp;', '&'), size)
