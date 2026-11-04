# -*- coding: utf-8 -*-
"""Reading a glass supplier's price list: type, thickness, price per sqft.

Free of Odoo imports, like rate_paste.py, so scripts/check_glass_paste.py
runs this very code against the Ghani list.

A row is three fields in this order: the glass TYPE, a THICKNESS with "mm",
and the PRICE. Tabs, runs of spaces and non-breaking spaces all separate
them; the price is always the last number on the line, and the thickness
the one with "mm" just before it. A line that does not fit that (a heading,
or a row with a second number) is not guessed at: it is handed back in
`skipped`, so nothing a pasted sheet contains is dropped silently.

One pasted row can mean several rates, and each becomes its own row:

- colours separated by "/" or listed in brackets: "Green/Brown 8mm 948.13"
  and "WC (Grn, Brw, Blue) 5mm 231.88" are one rate per colour;
- a thickness like "5mm/6mm" is one rate per thickness;
- "Ref." means reflective: a separate glass type "Ref. <colour>";
- WC and CC are kept exactly as written ("WC Green", "CC Grey"), with no
  guess at what they stand for.

A type is compared whole: "Ref. Grey" and "Grey" are different types and
are never merged.
"""
import re

COLOUR_WORDS = {'grn': 'Green', 'brw': 'Brown'}
PREFIXES = ('WC', 'CC')

# Every kind of space the sheet might use between fields, as plain space.
_ODD_SPACES = re.compile('[    　]')
_PRICE_AT_END = re.compile(r'(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*$')
_THICKNESS_AT_END = re.compile(
    r'(?P<thick>\d+(?:\.\d+)?\s*(?:mm)?(?:\s*/\s*\d+(?:\.\d+)?\s*(?:mm)?)*)\s*$',
    re.I)


def clean_line(raw):
    """One line with every kind of space made an ordinary one."""
    return _ODD_SPACES.sub(' ', raw or '').strip()


def norm_type(text):
    """Two spellings of one glass type compare equal. The whole text is
    compared, so 'Ref. Grey' ('refgrey') never equals 'Grey'."""
    return re.sub(r'[\s.\-_]+', '', (text or '').lower())


def _colour(word):
    word = word.strip()
    if not word:
        return ''
    lowered = COLOUR_WORDS.get(word.lower())
    if lowered:
        return lowered
    return ' '.join(part[:1].upper() + part[1:] for part in word.split())


def expand_type(text):
    """'Ref. Green/Brown' -> [('Ref. Green', True), ('Ref. Brown', True)]."""
    rest = (text or '').strip()
    reflective = False
    match = re.match(r'(?i)^ref\.?\s*(.*)$', rest)
    if match:
        reflective, rest = True, match.group(1).strip()
    prefix = ''
    match = re.match(r'(?i)^(%s)\b\s*(.*)$' % '|'.join(PREFIXES), rest)
    if match:
        prefix, rest = match.group(1).upper(), match.group(2).strip()
    inner = re.match(r'^\((.*)\)$', rest)
    if inner:
        rest = inner.group(1)
    colours = [_colour(part) for part in re.split(r'[/,]', rest)]
    colours = [c for c in colours if c] or ['']
    names = []
    for colour in colours:
        name = ' '.join(part for part in (prefix, colour) if part)
        if reflective:
            name = 'Ref. %s' % name if name else 'Ref.'
        names.append((name, reflective))
    return names


def parse_thickness(text):
    """'5mm/6mm' -> [5.0, 6.0]; '6 mm' -> [6.0]; '' -> []."""
    return [float(n) for n in re.findall(r'\d+(?:\.\d+)?', text or '')]


def thickness_label(mm):
    return '%smm' % ('%g' % mm)


def split_row(raw):
    """(type_text, thickness_text, price) of one line, or None when the
    line is not exactly type + thickness-with-mm + price."""
    line = clean_line(raw)
    price_match = _PRICE_AT_END.search(line)
    if not price_match:
        return None
    rest = line[:price_match.start()].rstrip()
    thick = _THICKNESS_AT_END.search(rest)
    if not thick or 'mm' not in thick.group('thick').lower():
        return None
    type_text = rest[:thick.start()].strip()
    if not type_text:
        return None
    return (type_text, thick.group('thick'),
            float(price_match.group(1).replace(',', '')))


def parse_glass_paste_report(text):
    """(rows, skipped): one dict per (type, thickness) read, and the lines
    that were NOT read because they contain a number but are not a
    type + thickness + price row. A line with no digit at all (a heading)
    is not reported."""
    rows, skipped = [], []
    for raw in (text or '').splitlines():
        line = clean_line(raw)
        if not line:
            continue
        parsed = split_row(line)
        if not parsed:
            if re.search(r'\d', line):
                skipped.append(line)
            continue
        type_text, thick_text, price = parsed
        for name, reflective in expand_type(type_text):
            for mm in parse_thickness(thick_text):
                rows.append({
                    'type': name, 'reflective': reflective,
                    'thickness_mm': mm, 'thickness': thickness_label(mm),
                    'price': price})
    return rows, skipped


def parse_glass_paste(text):
    """Just the rows. See parse_glass_paste_report for what is left out."""
    return parse_glass_paste_report(text)[0]
