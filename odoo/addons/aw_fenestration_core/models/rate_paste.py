# -*- coding: utf-8 -*-
"""Reading a vendor's rate sheet from pasted text.

Odoo-free, like formula.py, so a test can hold it to the real thing.

A vendor's sheet is a row per profile and thickness: a code, a thickness,
a series, then one rate per finish. The columns are described once per
vendor (aw.vendor.layout); this turns pasted rows into
{code, thickness, series, rates} using that description.
"""
import re

KINDS = ('code', 'thickness', 'series', 'finish', 'skip')


_PREFIX_AND_NUMBER = re.compile(r'^([A-Za-z]+)[\s.\-]*(\d.*)$')


def canonical_code(code):
    """Letters, an optional separator (none, space, dot or hyphen), then
    the number and suffix -- always written with a hyphen: "D38F",
    "D 38F" and "D.40" are "D-38F" and "D-40". Anything not shaped like
    that is returned trimmed and otherwise as it is."""
    code = (code or '').strip()
    match = _PREFIX_AND_NUMBER.match(code)
    if not match:
        return code
    return '%s-%s' % (match.group(1).upper(), match.group(2).strip())


def normalise_code(code):
    """Case, spaces, hyphens and underscores do not distinguish a vendor
    code: "D35" is "D-35", and so is "D.40" "D-40". Suffix words are kept
    ("D-35 M.F" stays a different profile from "D-35")."""
    return re.sub(r'[\s\-_]+', '', canonical_code(code).upper())


def normalise_text(text):
    return re.sub(r'\s+', '', (text or '').upper())


def parse_number(cell):
    """A rate from a cell: "1,234.5" -> 1234.5; blank or text -> None."""
    cell = (cell or '').strip().replace(',', '')
    if not cell:
        return None
    try:
        return float(cell)
    except ValueError:
        return None


def clean(text):
    """What a spreadsheet copy can carry that a person cannot see: a BOM,
    non-breaking spaces, CRLF line ends."""
    return ((text or '').replace('\ufeff', '').replace('\xa0', ' ')
            .replace('\r\n', '\n').replace('\r', '\n'))


def split_row(line, kinds):
    """The cells of one pasted row, padded to the layout.

    Tab-separated is what a spreadsheet gives. A row typed with spaces is
    also accepted; there, a blank Series cell leaves one token fewer than
    there are columns, and the blank is put back where the layout says
    the series column is.
    """
    width = len(kinds)
    if '\t' in line:
        cells = line.split('\t')
    else:
        cells = re.split(r'\s{2,}', line.strip())
        if len(cells) != width:
            cells = line.split()
        if len(cells) == width - 1 and 'series' in kinds:
            cells.insert(kinds.index('series'), '')
    # An empty cell between two tabs is a cell: it must not shift the
    # columns after it. Excel can also wrap a cell in quotes.
    cells = [cell.strip().strip('"').strip() for cell in cells]
    return (cells + [''] * width)[:width]


def parse_paste(text, kinds):
    """Rows from pasted text.

    `kinds` is the layout's column kinds in order, e.g.
    ['code', 'thickness', 'series', 'finish', 'finish', ...]. Returns a
    list of {code, thickness, series, rates}, `rates` being one number or
    None per finish column. A header row (no number under any finish
    column) is skipped, and a blank Series takes the row above's.
    """
    rows = []
    series = ''
    finish_at = [i for i, kind in enumerate(kinds) if kind == 'finish']
    for line in clean(text).split('\n'):
        if not line.strip():
            continue
        cells = split_row(line, kinds)
        rates = [parse_number(cells[i]) for i in finish_at]
        if not any(rate is not None for rate in rates):
            continue            # the header, or a row with no rates
        pick = lambda kind: next(
            (cells[i] for i, k in enumerate(kinds) if k == kind), '')
        row_series = pick('series') or series
        series = row_series
        rows.append({
            'code': pick('code'),
            'thickness': pick('thickness'),
            'series': row_series,
            'rates': rates,
        })
    return rows
