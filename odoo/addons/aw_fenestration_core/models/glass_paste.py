# -*- coding: utf-8 -*-
"""Reading a glass supplier's price list: type, thickness, price per sqft.

Free of Odoo imports, like rate_paste.py, so scripts/check_glass_paste.py
runs this very code against the Ghani list.

One pasted row can mean several rates, and each becomes its own row:

- colours separated by "/" or listed in brackets: "Green/Brown 8mm 948.13"
  and "WC (Grn, Brw, Blue) 5mm 231.88" are one rate per colour;
- a thickness like "5mm/6mm" is one rate per thickness;
- "Ref." means reflective: a separate glass type "Ref. <colour>";
- WC and CC are kept exactly as written ("WC Green", "CC Grey"), with no
  guess at what they stand for.
"""
import re

COLOUR_WORDS = {'grn': 'Green', 'brw': 'Brown'}
PREFIXES = ('WC', 'CC')

_THICKNESS = (r'(?=[\d.\s/]*mm)\d+(?:\.\d+)?\s*(?:mm)?'
              r'(?:\s*/\s*\d+(?:\.\d+)?\s*(?:mm)?)*')
_ROW = re.compile(
    r'^\s*(?P<type>.+?)[\s\t]+(?P<thick>%s)[\s\t]+(?P<price>\d[\d,]*(?:\.\d+)?)\s*$'
    % _THICKNESS, re.I)


def norm_type(text):
    """Two spellings of one glass type compare equal."""
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


def parse_glass_paste(text):
    """Rows of a pasted price list -> one dict per (type, thickness):
    {'type', 'reflective', 'thickness_mm', 'thickness', 'price'}.
    Lines that are not a row (headings, blanks) are ignored."""
    rows = []
    for raw in (text or '').splitlines():
        match = _ROW.match(raw)
        if not match:
            continue
        price = float(match.group('price').replace(',', ''))
        for name, reflective in expand_type(match.group('type')):
            for mm in parse_thickness(match.group('thick')):
                rows.append({
                    'type': name, 'reflective': reflective,
                    'thickness_mm': mm, 'thickness': thickness_label(mm),
                    'price': price})
    return rows
