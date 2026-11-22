# -*- coding: utf-8 -*-
"""Cutting one report into several wkhtmltopdf runs (Odoo-free, so
`scripts/check_print_chunks.py` runs the real functions).

Why: wkhtmltopdf's memory grows with the size of the document it is given (about 31 MB
for each window sheet), and Odoo's worker runs it under `limit_memory_hard` (1.25 GiB of
address space). A quote of 100 windows died with "Thread creation error" (-11) at
1.28 GB. Run in groups, the peak depends on the group and not on the quote.

Two shapes of report are cut:

* several bodies (a report with an external layout makes one body per record: the
  window sheets, one per window): the bodies are dealt out in groups;
* ONE body made of many units (the Elevation Sheets, the sticker pages): the template
  puts START in front of each unit and END after the last one, and the body is cut
  between them, keeping what is before the first START and after END in every part.

A page break written at the end of a unit is taken off the last unit of a part, or the
engine adds an empty page at the end of each run.
"""
import copy
import re

import lxml.html

START = '<div class="o_aw_split"></div>'
END = '<div class="o_aw_split_end"></div>'
BREAK = 'page-break-after: always;'
DEFAULT_PER_RUN = 10      # weight a run may hold; a window or a sheet weighs 1

_START_RE = re.compile(
    r'<div class="o_aw_split"(?: data-weight="([\d.]+)")?>\s*</div>')
_END_RE = re.compile(r'<div class="o_aw_split_end">\s*</div>')
_PART_RE = re.compile(r'(Page\s*)(<span class="page">)')


def start_marker(weight=None):
    """The marker a template writes in front of a unit; `weight` says how much
    of a run's room it takes (default 1: a window sheet's worth)."""
    if weight is None:
        return START
    return '<div class="o_aw_split" data-weight="%s"></div>' % weight


def split_units(body):
    """(prefix, [(unit, weight)], suffix) of a body made of marked units, or
    None. Plain strings out, always: a body Odoo renders is a `Markup`, and a
    Markup ESCAPES any plain string added to it, so a body put back together
    from Markup and str pieces printed its own tags as text."""
    body = str(body)
    starts = list(_START_RE.finditer(body))
    ends = list(_END_RE.finditer(body))
    if not starts or not ends or ends[-1].start() < starts[0].end():
        return None
    prefix = body[:starts[0].start()]
    suffix = body[ends[-1].end():]
    units = []
    for i, found in enumerate(starts):
        stop = (starts[i + 1].start() if i + 1 < len(starts)
                else ends[-1].start())
        units.append((body[found.end():stop], float(found.group(1) or 1)))
    return prefix, units, suffix


def _without_trailing_break(unit):
    at = unit.rfind(BREAK)
    return unit if at < 0 else unit[:at] + unit[at + len(BREAK):]


def expand(bodies, per_run=DEFAULT_PER_RUN):
    """[(source body index, body, weight)]: every body that is made of units is
    cut into parts whose units weigh at most `per_run` together (a part has at
    least one unit); other bodies stay whole with weight 1. The markers are
    taken out whether or not the body is cut."""
    items = []
    for index, body in enumerate(bodies):
        body = str(body)
        cut = split_units(body)
        if cut is None:
            items.append((index, body, 1.0))
            continue
        prefix, units, suffix = cut
        part, weight = [], 0.0
        parts = []
        for unit, w in units:
            if part and weight + w > per_run:
                parts.append((part, weight))
                part, weight = [], 0.0
            part.append(unit)
            weight += w
        parts.append((part, weight))
        for units_of_part, total in parts:
            units_of_part[-1] = _without_trailing_break(units_of_part[-1])
            items.append((index, prefix + ''.join(units_of_part) + suffix,
                          min(total, per_run)))
    return items


def was_cut(bodies):
    """True when one of the bodies is made of units (so it may be printed in
    parts that number their own pages)."""
    return any(split_units(body) for body in bodies)


def runs(items, per_run=DEFAULT_PER_RUN):
    """The items dealt into runs of at most `per_run` weight each (a run has at
    least one item): lists of (source body index, body, weight)."""
    groups, group, weight = [], [], 0.0
    for item in items:
        if group and weight + item[2] > per_run:
            groups.append(group)
            group, weight = [], 0.0
        group.append(item)
        weight += item[2]
    if group:
        groups.append(group)
    return groups


def label_part(footer, number, total):
    """The footer with "Part n of N, " in front of its page number, for a report
    printed in parts that each count their own pages."""
    if not footer:
        return footer
    return _PART_RE.sub(
        lambda m: 'Part %d of %d, %s%s' % (
            number, total, m.group(1), m.group(2)),
        footer, count=1)


def slice_children(html, element_id, indexes):
    """The header (or footer) html with only the children that belong to the
    bodies of one run. Odoo makes one child per source body; the page script
    picks `children[n]` for the n-th body of the run, so the n-th child kept is
    the one of the n-th body (a body cut in parts repeats its own)."""
    if not html:
        return html
    document = lxml.html.document_fromstring(html)
    holder = document.get_element_by_id(element_id, None)
    if holder is None:
        return html
    children = list(holder)
    if not children:
        return html
    for child in children:
        holder.remove(child)
    for index in indexes:
        holder.append(copy.deepcopy(children[min(index, len(children) - 1)]))
    return lxml.html.tostring(
        document, doctype='<!DOCTYPE html>', encoding='unicode')
