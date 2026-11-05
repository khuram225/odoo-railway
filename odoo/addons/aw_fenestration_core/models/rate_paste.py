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


_FULL_CODE = re.compile(r'^[A-Za-z]+[-\s]*\d')
_BASE_AND_SUFFIX = re.compile(r'^(.*\d)([A-Za-z]*)$')


def split_codes(code):
    """A code written with a slash is one row for two codes.

    Returns [(code, ambiguous)]:
      "D-48 A/ET-48 A"  both parts full codes   -> D-48A, ET-48A
      "D-42F / H"       second part a bare suffix -> D-42F, D-42H
      anything else with a slash stays ONE line, flagged ambiguous.
    A code without a slash is returned as it is.
    """
    code = (code or '').strip()
    if '/' not in code:
        return [(code, False)]
    parts = [part.strip() for part in code.split('/')]
    if len(parts) != 2 or not all(parts):
        return [(code, True)]
    first, second = (re.sub(r'\s+', '', part) for part in parts)
    if _FULL_CODE.match(parts[0]) and _FULL_CODE.match(parts[1]):
        return [(first, False), (second, False)]
    base = _BASE_AND_SUFFIX.match(first)
    if _FULL_CODE.match(parts[0]) and base and re.fullmatch(
            r'[A-Za-z]+', second):
        return [(first, False), (base.group(1) + second, False)]
    return [(code, True)]


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
        for code, ambiguous in split_codes(pick('code')):
            rows.append({
                'code': code,
                'thickness': pick('thickness'),
                'series': row_series,
                'rates': list(rates),
                'ambiguous': ambiguous,
            })
    return rows


# --------------------------------------------------------------------------
# The safe reading of a pasted sheet
# --------------------------------------------------------------------------
# parse_paste() above reads by POSITION and forgives everything: a sheet
# missing its code column, a dropped cell or an extra one was accepted, the
# prices slid one column along and landed on the wrong finish. validate_paste()
# is what the paste is read with now. It reads by the header's NAMES when the
# paste has a header row, counts the cells of every row, and stops (it does not
# guess) on anything that could put a price on the wrong profile or finish.

NO_PRICE = ('', '-', '\u2013', '\u2014')

# What a header cell may say for the three non-price kinds, besides the
# layout's own header text. Compared with case, spaces and punctuation gone.
KIND_ALIASES = {
    'code': {'code', 'profile', 'profilecode', 'profilename', 'section',
             'sectionno', 'sectionnumber', 'secno', 'sec', 'item', 'itemcode'},
    'thickness': {'thickness', 'thick', 'thk'},
    'series': {'series'},
}


def header_key(text):
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


def split_cells(line, expected, kinds=None, has_header=False):
    """The cells of one row, NOT padded. A tab separates cells; a row typed
    with spaces is split on runs of two or more, else on any space. A blank
    Series cell in a space-typed row (one token short) is put back only when
    there is no header and the row starts like a profile code, so that a row
    missing its CODE column is not mistaken for one with a blank series."""
    if '\t' in line:
        cells = line.split('\t')
    else:
        cells = re.split(r'\s{2,}', line.strip())
        if len(cells) != expected:
            cells = line.split()
        if (not has_header and kinds and len(cells) == expected - 1
                and 'series' in kinds and cells
                and _FULL_CODE.match(cells[0])):
            cells.insert(kinds.index('series'), '')
    return [cell.strip().strip('"').strip() for cell in cells]


def validate_paste(text, columns):
    """Read pasted rows against a layout, or say exactly what is wrong.

    `columns` is the layout in order: [{'kind', 'header', 'finish'}, ...]
    with kind in code / thickness / series / finish / skip. Returns

        {'rows': [{line, code, thickness, series, rates, ambiguous}],
         'errors': [{'line': n, 'message': text}],
         'header': [header cells] or None,
         'summary': {'rows', 'no_price_cells', 'no_price_rows'}}

    `rates` has one entry per FINISH column of the layout, in order: a
    number, or None for "no price" -- never 0. Any error means nothing
    should be written.
    """
    kinds = [c['kind'] for c in columns]
    finish_at = [i for i, kind in enumerate(kinds) if kind == 'finish']
    errors = []
    rows = []
    summary = {'rows': 0, 'no_price_cells': 0, 'no_price_rows': 0}

    numbered = [(n, line) for n, line in
                enumerate(clean(text).split('\n'), start=1) if line.strip()]
    if not numbered:
        return {'rows': [], 'errors': [{'line': 0, 'message':
                'There is nothing to read.'}], 'header': None,
                'summary': summary}

    # -- the header row, if there is one --------------------------------------
    first_no, first_line = numbered[0]
    first_cells = split_cells(first_line, len(columns))
    header = None
    mapping = list(range(len(columns)))
    expected = len(columns)
    if not any(parse_number(cell) is not None for cell in first_cells):
        header = first_cells
        numbered = numbered[1:]
        mapping = []
        used = set()
        for position, name in enumerate(header, start=1):
            key = header_key(name)
            found = None
            if key:
                for index, column in enumerate(columns):
                    if index in used:
                        continue
                    names = {header_key(column.get('header')),
                             header_key(column.get('finish'))}
                    names.discard('')
                    names |= KIND_ALIASES.get(column['kind'], set())
                    if key in names:
                        found = index
                        break
            if found is None:
                errors.append({'line': first_no, 'message': (
                    "Unknown header %r (column %d). Add it to the layout "
                    "first." % (name, position) if name.strip() else
                    "Column %d has no header." % position)})
            else:
                used.add(found)
            mapping.append(found)
        if 'code' not in [kinds[i] for i in mapping if i is not None]:
            errors.append({'line': first_no, 'message':
                           "The header has no code column."})
        expected = len(header)
        if errors:
            return {'rows': [], 'errors': errors, 'header': header,
                    'summary': summary}

    # -- the rows ---------------------------------------------------------------
    series = ''
    seen = {}
    for line_no, line in numbered:
        cells = split_cells(line, expected, kinds, has_header=header is not None)
        if len(cells) != expected:
            errors.append({'line': line_no, 'message': (
                "Row %d has %d cells; %s has %d. A cell was dropped or added."
                % (line_no, len(cells),
                   'the header' if header else 'the layout', expected))})
            continue
        values = {}
        problem = False
        for position, index in enumerate(mapping):
            if index is None:
                continue
            values[index] = cells[position]
        code_cell = next((v for i, v in values.items() if kinds[i] == 'code'), '')
        if not code_cell.strip():
            errors.append({'line': line_no, 'message':
                           "Row %d has no code." % line_no})
            continue
        rates = []
        for index in finish_at:
            raw = values.get(index, '').strip()
            name = (columns[index].get('header') or columns[index].get('finish')
                    or 'price %d' % (finish_at.index(index) + 1))
            if raw in NO_PRICE:
                rates.append(None)
                continue
            number = parse_number(raw)
            if number is None:
                errors.append({'line': line_no, 'message': (
                    "Row %d: %r under %s is not a number." % (line_no, raw, name))})
                problem = True
                rates.append(None)
            elif number <= 0:
                errors.append({'line': line_no, 'message': (
                    "Row %d: the price %s under %s is %s."
                    % (line_no, raw, name, 'zero' if number == 0 else 'negative'))})
                problem = True
                rates.append(None)
            else:
                rates.append(number)
        if problem:
            continue
        pick = lambda kind: next(
            (v for i, v in values.items() if kinds[i] == kind), '')
        row_series = pick('series') or series
        series = row_series
        for code, ambiguous in split_codes(pick('code')):
            thickness = pick('thickness')
            for slot, price in enumerate(rates):
                if price is None:
                    continue
                key = (normalise_code(code), normalise_text(thickness), slot)
                if key in seen and seen[key][1] != price:
                    column = columns[finish_at[slot]]
                    errors.append({'line': line_no, 'message': (
                        "Rows %d and %d both price %s %s %s, at %s and %s."
                        % (seen[key][0], line_no, canonical_code(code), thickness,
                           column.get('header') or column.get('finish'),
                           seen[key][1], price))})
                seen.setdefault(key, (line_no, price))
            rows.append({'line': line_no, 'code': code, 'thickness': thickness,
                         'series': row_series, 'rates': list(rates),
                         'ambiguous': ambiguous})
            summary['rows'] += 1
            missing = sum(1 for price in rates if price is None)
            summary['no_price_cells'] += missing
            if missing == len(rates):
                summary['no_price_rows'] += 1
    return {'rows': rows if not errors else [], 'errors': errors,
            'header': header, 'summary': summary}
