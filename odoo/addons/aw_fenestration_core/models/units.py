# -*- coding: utf-8 -*-
"""Inches and soot, in and out of millimetres. No Odoo imports.

The workshop thinks in inches and soot (1 soot = 1/8 in = 3.175 mm); the
database stores millimetres and only millimetres -- inches live nowhere
but on screen.

ONE DISPLAY RULE for every length a person reads: inches, rounded to the
nearest 1/16. No decimals, no feet, no Unicode fraction glyphs. Two
styles of the same number:

  style="fraction" (the default) -- a reduced ASCII fraction:
    to_display(1828.8)  -> "72"        to_display(1790.7) -> "70 1/2"
    to_display(866.8)   -> "34 1/8"    to_display(846.1)  -> "33 5/16"
    to_display(-38.1)   -> "-1 1/2"    to_display(0)      -> "0"

  style="soot" -- inches, a dash, then soot (1/8 in); half a soot is .5:
    to_display(1209.2, "soot") -> "47-5"      (47 5/8 in)
    to_display(1179.2, "soot") -> "46-3.5"    (46 7/16 in)
    to_display(866.8,  "soot") -> "34-1"      to_display(3657.6, "soot") -> "144"
    A length under an inch keeps the leading zero: "0-4", never a bare "4".

The fraction style is for reading (quote text, schedule, drawing); soot is
for the workshop (cut list, entry boxes, labels). Either way the value is
rounded to 1/16 in first.

And a forgiving parser for what people type:

    to_mm("72")        72 in            -> 1828.8
    to_mm("34.125")    decimal inches   -> 866.78  (accepted, never shown)
    to_mm("34 1/8")    mixed number     -> 866.78
    to_mm("34-1/8")    dash + fraction  -> 866.78
    to_mm("33 5/16")   to the sixteenth -> 846.14
    to_mm("33-5/16")   same
    to_mm("33-6")      dash + number is SOOT: 33 in + 6 soot -> 857.25
    to_mm("33-6.5")    half a soot too  -> 858.84
    to_mm("3s")        3 soot           -> 9.53
    to_mm("-1 1/2")    signed           -> -38.1
    to_mm("+3s")       signed soot      -> 9.53
    to_mm("1829mm")    millimetres      -> 1829.0

Results are rounded to 0.01 mm, not 0.1: "33-6" is exactly 857.25 and a
tenth-of-a-millimetre rounding would make it 857.2 or 857.3 -- the one
number the workshop's own rule is checked against.

The JavaScript twin is formatInches / parseInches in
design_configurator.js; scripts/check_inch_display.mjs holds both to the
same test vectors.
"""
import re

MM_PER_INCH = 25.4
MM_PER_SOOT = MM_PER_INCH / 8          # 3.175

# Accepted on input only; the display never writes them.
_FRACTIONS = {
    '½': 0.5, '¼': 0.25, '¾': 0.75,
    '⅓': 1 / 3, '⅔': 2 / 3,
    '⅛': 0.125, '⅜': 0.375, '⅝': 0.625, '⅞': 0.875,
}

_NUMBER = r'\d+(?:\.\d+)?'
_FRACTION = r'\d+/\d+'


def _inches(text):
    """A bare inch quantity: 72, 34.125, '34 1/8', '1/8', '34<glyph>'."""
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
    elif re.fullmatch(_NUMBER + r'\s*s', raw):
        value = float(raw[:-1].strip()) * MM_PER_SOOT
    else:
        dash = re.fullmatch(
            r'(' + _NUMBER + r')\s*-\s*(' + _FRACTION + r'|' + _NUMBER + r')',
            raw)
        if dash:
            whole, after = dash.group(1), dash.group(2)
            if '/' in after:          # 34-1/8 : inches and a fraction
                value = _inches('%s %s' % (whole, after)) * MM_PER_INCH
            else:                     # 33-6   : inches and soot
                value = (float(whole) * MM_PER_INCH
                         + float(after) * MM_PER_SOOT)
        else:
            value = _inches(raw) * MM_PER_INCH
    return round(sign * value, 2)


def edited_mm(text, current_mm, style='fraction'):
    """What a text field's inverse should store: `current_mm` when the
    text is just the display of it handed back (the field was not
    edited), otherwise the parsed text. Without this, saving a form
    would snap every untouched length to the nearest 1/16 in."""
    if (text or '').strip() == to_display(current_mm, style):
        return current_mm
    return to_mm(text)


def to_display(mm, style='fraction'):
    """Millimetres as inches to the nearest 1/16.

    fraction: a reduced ASCII fraction -- 866.8 -> '34 1/8',
    1828.8 -> '72', -38.1 -> '-1 1/2'.
    soot:     inches, dash, soot -- 866.8 -> '34-1', 1209.2 -> '47-5',
    1179.2 -> '46-3.5' (half a soot is .5).

    Rounded to sixteenths BEFORE splitting into whole and remainder, so a
    value a hair under a whole inch (12 x 25.4 is 304.79999999999995 in
    float) reads '12', never '11 16/16'.
    """
    mm = float(mm or 0.0)
    sign = '-' if mm < 0 else ''
    sixteenths = int(round(abs(mm) / MM_PER_INCH * 16))
    whole, rest = divmod(sixteenths, 16)
    if not rest:
        return '%s%d' % (sign if whole else '', whole)
    if style == 'soot':
        soot = rest / 2               # a sixteenth is half a soot
        text = '%d' % soot if rest % 2 == 0 else '%.1f' % soot
        return '%s%d-%s' % (sign, whole, text)
    num, den = rest, 16
    while num % 2 == 0:
        num //= 2
        den //= 2
    fraction = '%d/%d' % (num, den)
    if whole:
        return '%s%d %s' % (sign, whole, fraction)
    return '%s%s' % (sign, fraction)
