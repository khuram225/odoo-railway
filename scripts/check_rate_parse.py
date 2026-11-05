#!/usr/bin/env python3
"""A pasted rate sheet is read safely or not at all.

Runs the REAL validator, `validate_paste` out of
aw_fenestration_core/models/rate_paste.py (Odoo-free for exactly this).
The bug it guards: a sheet pasted without its code column was accepted,
every price slid one column along and landed on the wrong finish. Each
case below is one way a paste goes wrong, or the good paste that must
still go through.
"""
import importlib.util
import sys
from pathlib import Path

MODULE = (Path(__file__).resolve().parent.parent / 'odoo' / 'addons'
          / 'aw_fenestration_core' / 'models' / 'rate_paste.py')
spec = importlib.util.spec_from_file_location('aw_rate_paste', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
validate = mod.validate_paste

LAYOUT = [
    {'kind': 'code', 'header': 'Section #', 'finish': ''},
    {'kind': 'thickness', 'header': 'Thickness', 'finish': ''},
    {'kind': 'series', 'header': 'Series', 'finish': ''},
    {'kind': 'finish', 'header': 'DULL', 'finish': 'Natural'},
    {'kind': 'finish', 'header': 'BRO', 'finish': 'Brown'},
    {'kind': 'finish', 'header': 'H.23', 'finish': 'H23'},
]
T = '\t'
HEADER = T.join(['Section #', 'Thickness', 'Series', 'DULL', 'BRO', 'H.23'])

failed = 0


def case(name, text, check):
    global failed
    result = validate(text, LAYOUT)
    problem = check(result)
    ok = not problem
    failed += not ok
    print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else '  -> ' + str(problem)))


def stops(*words):
    """The paste is refused, and the messages name each word."""
    def check(result):
        if not result['errors'] or result['rows']:
            return 'expected a stop, got %s' % result
        text = ' '.join(e['message'] for e in result['errors'])
        missing = [w for w in words if w not in text]
        return 'message lacks %s: %s' % (missing, text) if missing else ''
    return check


# a good list, with and without its header
GOOD = '\n'.join([
    HEADER,
    T.join(['D-38', '1.6MM', 'S1', '100', '110', '120']),
    T.join(['D-40', '2MM', '', '200', '210', '220']),
])
case('a good list with its header', GOOD, lambda r: (
    '' if not r['errors'] and r['summary']['rows'] == 2
    and r['rows'][0]['rates'] == [100.0, 110.0, 120.0]
    and r['rows'][1]['series'] == 'S1'
    else 'got %s' % r))
case('a good list without a header', '\n'.join(GOOD.split('\n')[1:]),
     lambda r: '' if not r['errors'] and len(r['rows']) == 2 else 'got %s' % r)

# columns are matched by NAME: a different order puts prices under the right finish
REORDERED = '\n'.join([
    T.join(['Thickness', 'Section #', 'BRO', 'DULL', 'H.23', 'Series']),
    T.join(['1.6MM', 'D-38', '110', '100', '120', 'S1']),
])
case('headers in another order are read by name', REORDERED, lambda r: (
    '' if not r['errors'] and r['rows'][0]['code'] == 'D-38'
    and r['rows'][0]['rates'] == [100.0, 110.0, 120.0]
    and r['rows'][0]['series'] == 'S1' else 'got %s' % r))

# the reported bug: no code column
case('a missing code column (header)', '\n'.join([
    T.join(['Thickness', 'Series', 'DULL', 'BRO', 'H.23']),
    T.join(['1.6MM', 'S1', '100', '110', '120'])]), stops('no code column'))
case('a missing code column (no header): the row is one cell short', T.join(
    ['1.6MM', 'S1', '100', '110', '120']), stops('All rows have 5 cells', 'this layout has 6'))
case('a missing code column typed with spaces is not a blank series',
     '1.6MM  100  110  120  130', stops('All rows have 5 cells'))

# cell counts
case('a dropped middle cell', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '100', '120'])]),
     stops('Row 2', '5 cells', 'header has 6'))
case('an extra cell', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '100', '110', '120', '130'])]),
     stops('Row 2', '7 cells'))
case('the offending row is named among good ones', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '100', '110', '120']),
    T.join(['D-39', '1.6MM', 'S1', '100', '120']),
    T.join(['D-40', '1.6MM', 'S1', '100', '110', '120'])]), stops('Row 3'))

# headers
case('an unknown header', '\n'.join([
    T.join(['Section #', 'Thickness', 'Series', 'DULL', 'BRO', 'CHROME']),
    T.join(['D-38', '1.6MM', 'S1', '100', '110', '120'])]), stops('CHROME'))
case('an empty header cell', '\n'.join([
    T.join(['Section #', 'Thickness', 'Series', 'DULL', '', 'H.23']),
    T.join(['D-38', '1.6MM', 'S1', '100', '110', '120'])]), stops('no header'))

# prices
case('text in a price', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '100', 'abc', '120'])]),
     stops('Row 2', "'abc'", 'BRO', 'not a number'))
case('a zero price', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '0', '110', '120'])]),
     stops('Row 2', 'zero', 'DULL'))
case('a negative price', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '100', '-5', '120'])]),
     stops('Row 2', 'negative', 'BRO'))
case('the same product, thickness and finish twice with different prices', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '100', '110', '120']),
    T.join(['D 38', '1.6mm', 'S1', '105', '110', '120'])]),
     stops('Rows 2 and 3', 'D-38', 'DULL', '100.0', '105.0'))
case('the same key twice with the SAME price is harmless', '\n'.join([
    HEADER, T.join(['D-38', '1.6MM', 'S1', '100', '110', '120']),
    T.join(['D-38', '1.6MM', 'S1', '100', '110', '120'])]),
     lambda r: '' if not r['errors'] else 'got %s' % r)

# an empty price is "no price", never 0
EMPTY = '\n'.join([HEADER, T.join(['D-38', '1.6MM', 'S1', '100', '', '120']),
                   T.join(['D-40', '2MM', 'S1', '-', '', ''])])
case('an empty price is no price, counted, never 0', EMPTY, lambda r: (
    '' if not r['errors'] and r['rows'][0]['rates'] == [100.0, None, 120.0]
    and all(p != 0 for row in r['rows'] for p in row['rates'])
    and r['summary']['no_price_cells'] == 4
    and r['summary']['no_price_rows'] == 1 else 'got %s' % r))

# a typed row with a blank series (spaces) still works when the layout has one
case('a space-typed row with a blank series', 'B-6  NOR  136 147 137',
     lambda r: '' if not r['errors'] and r['rows'][0]['code'] == 'B-6'
     and r['rows'][0]['rates'] == [136.0, 147.0, 137.0] else 'got %s' % r)
case('nothing to read', '  \n \n', stops('nothing to read'))

# -- the wrong vendor's sheet, said once ---------------------------------------
CHAWLA = [
    {'kind': 'code', 'header': 'profile_code', 'finish': ''},
    {'kind': 'thickness', 'header': 'thickness', 'finish': ''},
] + [{'kind': 'finish', 'header': h, 'finish': h} for h in (
    'natural', 'h23_pc_ral', 'brown_pc_sahara', 'black_multi_ss_dull',
    'designer', 'c_shine')]
PREMIUM = LAYOUT[:3] + [{'kind': 'finish', 'header': h, 'finish': h} for h in (
    'DULL', 'BRO', 'H.23', 'RAL P.C', 'BLACK', 'SHARA', 'WOOD')]
OTHERS_FOR_CHAWLA = [{'vendor': 'Premium', 'width': len(PREMIUM)}]
OTHERS_FOR_PREMIUM = [{'vendor': 'Chawla', 'width': len(CHAWLA)}]
PREMIUM_SHEET = '\n'.join([
    T.join(['Section #', 'Thickness', 'Series', 'DULL', 'BRO', 'H.23', 'RAL P.C',
            'BLACK', 'SHARA', 'WOOD']),
    T.join(['D-38', '1.6MM', 'S1'] + ['100'] * 7),
    T.join(['D-40', '2MM', 'S1'] + ['200'] * 7),
    T.join(['D-41', '2MM', 'S1'] + ['300'] * 7)])
CHAWLA_SHEET = '\n'.join([
    T.join(['Profile Name', 'Thick', 'Natural', 'H23 PC RAL', 'Brown', 'Black',
            'Designer', 'C Shine']),
    T.join(['D-38', '1.6MM'] + ['100'] * 6),
    T.join(['D-40', '2MM'] + ['200'] * 6)])


def vendor_case(name, text, layout, others, words, not_words=()):
    global failed
    result = validate(text, layout, others)
    messages = [e['message'] for e in result['errors']]
    joined = ' '.join(messages)
    problem = ''
    if len(messages) != 1:
        problem = 'expected ONE line, got %d: %s' % (len(messages), messages)
    elif result['rows']:
        problem = 'rows were returned'
    else:
        missing = [w for w in words if w not in joined]
        present = [w for w in not_words if w in joined]
        if missing or present:
            problem = 'missing %s, unexpected %s in: %s' % (missing, present, joined)
    ok = not problem
    failed += not ok
    print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else '  -> ' + problem))


vendor_case('a whole Premium sheet pasted into a Chawla list, said once',
            PREMIUM_SHEET, CHAWLA, OTHERS_FOR_CHAWLA,
            ['All rows have 10 cells, this layout has 8',
             "another vendor's sheet", 'Check the vendor',
             'A sheet with 10 cells matches the layout of Premium'],
            not_words=['Row 2', 'Unknown header'])
vendor_case('a Chawla sheet pasted into a Premium list, said once',
            CHAWLA_SHEET, PREMIUM, OTHERS_FOR_PREMIUM,
            ['All rows have 8 cells, this layout has 10',
             'A sheet with 8 cells matches the layout of Chawla'],
            not_words=['Row 2'])
vendor_case('a sheet that matches no other vendor still says it once, without a name',
            '\n'.join([T.join(['a', 'b', 'c']), T.join(['D-1', '2MM', '5'])]),
            PREMIUM, OTHERS_FOR_PREMIUM,
            ['All rows have 3 cells, this layout has 10', 'Check the vendor'],
            not_words=['matches the layout'])
vendor_case('with no header, every row the wrong width',
            '\n'.join([T.join(['D-38', '1.6MM'] + ['100'] * 6),
                       T.join(['D-40', '2MM'] + ['200'] * 6)]),
            PREMIUM, OTHERS_FOR_PREMIUM,
            ['All rows have 8 cells, this layout has 10', 'Chawla'])

# one row with a dropped cell among good ones: the row, not a claim about the vendor
ONE_DROPPED = '\n'.join([
    T.join(['Section #', 'Thickness', 'Series', 'DULL', 'BRO', 'H.23']),
    T.join(['D-38', '1.6MM', 'S1', '100', '110', '120']),
    T.join(['D-39', '1.6MM', 'S1', '100', '120']),
    T.join(['D-40', '1.6MM', 'S1', '100', '110', '120'])])
result = validate(ONE_DROPPED, LAYOUT, OTHERS_FOR_PREMIUM)
messages = [e['message'] for e in result['errors']]
problem = ''
if len(messages) != 1 or 'Row 3' not in messages[0] or 'another vendor' in messages[0]:
    problem = str(messages)
failed += bool(problem)
print(('  ok   ' if not problem else '  FAIL ') + 'one row with a dropped cell names that row only'
      + ('' if not problem else '  -> ' + problem))

# several rows differ, but not all: each keeps its own error (the screen shows 5, then "and N more")
SOME = '\n'.join([HEADER] + [T.join(['D-%d' % n, '1.6MM', 'S1', '100', '110'])
                             for n in range(1, 9)]
                 + [T.join(['D-99', '1.6MM', 'S1', '100', '110', '120'])])
result = validate(SOME, LAYOUT, OTHERS_FOR_PREMIUM)
problem = ''
if len(result['errors']) != 8 or any('another vendor' in e['message'] for e in result['errors']):
    problem = '%d errors' % len(result['errors'])
failed += bool(problem)
print(('  ok   ' if not problem else '  FAIL ') + 'some rows differing keep their per-row errors'
      + ('' if not problem else '  -> ' + problem))

# every row short by the same cell, with a header: one sentence
ALL_DROPPED = '\n'.join([HEADER] + [T.join(['D-%d' % n, '1.6MM', 'S1', '100', '110'])
                                    for n in range(1, 4)])
result = validate(ALL_DROPPED, LAYOUT, OTHERS_FOR_PREMIUM)
messages = [e['message'] for e in result['errors']]
problem = '' if (len(messages) == 1
                 and 'All rows have 5 cells, the header has 6' in messages[0]) else str(messages)
failed += bool(problem)
print(('  ok   ' if not problem else '  FAIL ') + 'every row short by the same cell is one sentence'
      + ('' if not problem else '  -> ' + problem))

if failed:
    print('%d FAILED' % failed)
    sys.exit(1)
print('safe rate parse: all cases pass')
