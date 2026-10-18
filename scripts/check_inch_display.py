#!/usr/bin/env python3
"""The one inch display rule, in Python: both styles, the parser, and the
round trip. Loads aw_fenestration_core/models/units.py directly (it has
no Odoo imports), so it needs no database.

The JavaScript twin is checked by check_inch_display.mjs against the same
vectors; if one changes, so must the other.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UNITS = ROOT / 'odoo/addons/aw_fenestration_core/models/units.py'

spec = importlib.util.spec_from_file_location('aw_units', UNITS)
units = importlib.util.module_from_spec(spec)
spec.loader.exec_module(units)

FRACTION = [
    (1828.8, '72'), (1790.7, '70 1/2'), (866.8, '34 1/8'),
    (846.1, '33 5/16'), (304.79999999999995, '12'), (600, '23 5/8'),
    (1200, '47 1/4'), (731, '28 3/4'), (-38.1, '-1 1/2'), (0, '0'),
]
SOOT = [
    (1209.2, '47-5'), (3647.6, '143-5'), (1179.2, '46-3.5'),
    (3617.6, '142-3.5'), (3657.6, '144'), (866.8, '34-1'),
    (857.25, '33-6'), (0, '0'),
    (12.7, '0-4'),          # under an inch keeps its zero
    (-38.1, '-1-4'),
]
PARSE = [
    ('72', 1828.8), ('34.125', 866.78), ('34 1/8', 866.78),
    ('34-1/8', 866.78), ('33 5/16', 846.14), ('33-5/16', 846.14),
    ('33-6', 857.25), ('33-6.5', 858.84), ('3s', 9.53), ('+3s', 9.53),
    ('-1 1/2', -38.1), ('1829mm', 1829.0), ('', 0.0),
    ('47-5', 1209.675), ('47 5/8', 1209.675), ('47.625', 1209.675),
    ('1209mm', 1209.0), ('46-3.5', 1179.51),
]

failures = []


def check(ok, message):
    if not ok:
        failures.append(message)
    print('  %s %s' % ('ok  ' if ok else 'FAIL', message))


for mm, want in FRACTION:
    got = units.to_display(mm)
    check(got == want, 'fraction %s mm -> %r (want %r)' % (mm, got, want))
for mm, want in SOOT:
    got = units.to_display(mm, 'soot')
    check(got == want, 'soot %s mm -> %r (want %r)' % (mm, got, want))
for text, want in PARSE:
    got = units.to_mm(text)
    check(abs(got - want) < 0.02, 'to_mm(%r) -> %s (want %s)' % (text, got, want))
check(units.to_mm('33-6') == 857.25, 'to_mm("33-6") is exactly 857.25')

# Round trip: what is displayed reads back to the same sixteenth of an
# inch, in both styles, for a spread of lengths and their negatives.


def sixteenths(mm):
    return round(mm / units.MM_PER_INCH * 16)


bad = 0
checked = 0
value = 0.0
while value < 6000:
    for sign in (1, -1):
        mm = sign * value
        for style in ('fraction', 'soot'):
            back = units.to_mm(units.to_display(mm, style))
            checked += 1
            if sixteenths(back) != sixteenths(mm):
                bad += 1
                print('    round trip broke: %s %s -> %r -> %s' % (
                    style, mm, units.to_display(mm, style), back))
    value += 7.31
check(not bad, 'round trip: to_mm(to_display(x)) == x to 1/16 in '
      '(%s lengths, both styles, both signs)' % checked)

if failures:
    print('%s FAILURES' % len(failures))
    sys.exit(1)
print('Inch display (Python): every vector and the round trip hold.')
