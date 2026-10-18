# -*- coding: utf-8 -*-
"""Inches and soot, in and out of millimetres. No Odoo imports.

The workshop thinks in inches and soot (1 soot = 1/8 in = 3.175 mm); the
database stores millimetres and only millimetres -- inches live nowhere
but on screen.

    to_mm("72")        72 in          -> 1828.8
    to_mm("34.125")    decimal inches -> 866.775
    to_mm("34 1/8")    mixed number   -> 866.775
    to_mm("34⅛")  unicode fraction (also ½ ¼ ¾ ⅜ ⅝ ⅞)
    to_mm("33-6")      the dash is soot: 33 in + 6 soot -> 857.25
    to_mm("3s")        3 soot         -> 9.525
    to_mm("-1 1/2")    signed         -> -38.1
    to_mm("+3s")       signed soot    -> 9.525
    to_mm("1829mm")    millimetres    -> 1829.0

Results are rounded to 0.01 mm, not 0.1: "33-6" is exactly 857.25 and a
tenth-of-a-millimetre rounding would make it 857.2 or 857.3 -- the one
number the workshop's own rule is checked against.
"""
import re

MM_PER_INCH = 25.4
MM_PER_SOOT = MM_PER_INCH / 8          # 3.175

_FRACTIONS = {
    '½': 0.5, '¼': 0.25, '¾': 0.75,
    '⅓': 1 / 3, '⅔': 2 / 3,
    '⅛': 0.125, '⅜': 0.375, '⅝': 0.625, '⅞': 0.875,
}
_DISPLAY_FRACTIONS = {
    (1, 2): '½', (1, 4): '¼', (3, 4): '¾',
    (1, 8): '⅛', (3, 8): '⅜', (5, 8): '⅝', (7, 8): '⅞',
}

_NUMBER = r'\d+(?:\.\d+)?'


def _inches(text):
    """A bare inch quantity: 72, 34.125, '34 1/8', '1/8', '34<fraction>'."""
    text = text.strip()
    if not text:
        raise ValueError('empty')
    total = 0.0
    # a trailing unicode fraction, with or without a whole part
    if text[-1] in _FRACTIONS:
        total += _FRACTIONS[text[-1]]
        text = text[:-1].strip()
        if not text:
            return total
    for part in text.split():
        match = re.fullmatch(r'(\d+)/(\d+)', part)
        if match:
            total += int(match.group(1)) / int(match.group(2))
        elif re.fullmatch(_NUMBER, part):
            total += float(part)
        else:
            raise ValueError(part)
    return total


def to_mm(text):
    """Parse what somebody typed into millimetres; ValueError if it makes
    no sense. An empty string is 0."""
    if text is None:
        return 0.0
    raw = str(text).strip().lower().replace('″', '').replace('"', '')
    if not raw:
        return 0.0
    sign = 1.0
    if raw[0] in '+-':
        sign = -1.0 if raw[0] == '-' else 1.0
        raw = raw[1:].strip()
    if raw.endswith('mm'):
        value = float(raw[:-2].strip())
    elif raw.endswith('s') and re.fullmatch(_NUMBER + r'\s*s', raw):
        value = float(raw[:-1].strip()) * MM_PER_SOOT
    else:
        dash = re.fullmatch(r'(' + _NUMBER + r')\s*-\s*(' + _NUMBER + ')', raw)
        if dash:                      # 33-6 : inches - soot
            value = (float(dash.group(1)) * MM_PER_INCH
                     + float(dash.group(2)) * MM_PER_SOOT)
        else:
            value = _inches(raw) * MM_PER_INCH
    return round(sign * value, 2)


def to_display(mm):
    """Millimetres as inches to the nearest 1/16, e.g. 866.8 -> '34⅛'.

    Eighths, quarters and halves use the single-character fractions;
    sixteenths have none and read '3/16'. Whole inches have no fraction.
    """
    mm = float(mm or 0.0)
    sign = '-' if mm < 0 else ''
    sixteenths = int(round(abs(mm) / MM_PER_INCH * 16))
    whole, rest = divmod(sixteenths, 16)
    if not rest:
        return '%s%d' % (sign, whole)
    num, den = rest, 16
    while num % 2 == 0:
        num //= 2
        den //= 2
    fraction = _DISPLAY_FRACTIONS.get((num, den), '%d/%d' % (num, den))
    if whole:
        joiner = '' if (num, den) in _DISPLAY_FRACTIONS else ' '
        return '%s%d%s%s' % (sign, whole, joiner, fraction)
    return '%s%s' % (sign, fraction)
