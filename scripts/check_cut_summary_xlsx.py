#!/usr/bin/env python3
"""The cut summary workbook is built the way the brief says, or this fails.

Runs the REAL `build_cut_summary` out of
aw_fenestration_design/models/cut_summary_xlsx.py (Odoo-free for exactly this)
and reads the bytes back with openpyxl, a second library, so a mistake in how
it was written shows up as something Excel would see:

  * two sheets, "Summary" and "Cut list", both starting with batch, quote,
    date, plan state, bars and feet bought;
  * a stale plan carries the red note on both sheets, a current one carries
    none; an empty batch is refused with a message;
  * one block per profile; rows are windows in NATURAL order (W2 before W10);
    columns are the distinct lengths, longest first, workshop text over the
    exact mm; zero cells are blank; a profile with one length has one column;
  * every row ends with pieces and feet, every block with column totals, and
    the totals equal what the cuts add up to;
  * a window with two profiles is in two blocks;
  * the Cut list is flat, one row per cut, with the typed-length flag, an
    autofilter and a frozen header;
  * the file name.

Skips loudly when openpyxl or xlsxwriter is missing; CI installs both and runs
this --strict, so a skip there is a failure.
"""
import importlib.util
import io
import sys
from pathlib import Path

try:
    import openpyxl
    import xlsxwriter  # noqa: F401
except ImportError as error:
    print("skipping: openpyxl / xlsxwriter not installed (%s)" % error)
    sys.exit(0)

MODULE = (Path(__file__).resolve().parent.parent / 'odoo' / 'addons'
          / 'aw_fenestration_design' / 'models' / 'cut_summary_xlsx.py')
spec = importlib.util.spec_from_file_location('aw_cut_summary_xlsx', MODULE)
x = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x)

failures = []


def check(label, ok, detail=''):
    if not ok:
        failures.append("%s %s" % (label, detail))


def cut(window, location, block, code, mm, text, bar=1, typed=False,
        panel=1, angle='45'):
    return {'window': window, 'location': location, 'panel': panel,
            'code': code, 'thickness': '1.2', 'finish': 'Natural',
            'position': 'Outer Frame - Top', 'length_text': text,
            'length_mm': mm, 'angle': angle, 'bar_no': bar, 'typed': typed,
            'block': block}


CUTS = (
    # frame profile: W10 listed first on purpose, to prove the natural sort
    [cut('W10', 'Hall', 1, 'RE-8', 1200.0, '47-2')] * 2
    + [cut('W2', 'Kitchen', 1, 'RE-8', 1200.0, '47-2')] * 2
    + [cut('W2', 'Kitchen', 1, 'RE-8', 900.0, '35-3', bar=2, typed=True)] * 2
    + [cut('W1', 'Lounge', 1, 'RE-8', 1500.0, '59-0', bar=2)]
    # the same windows' second profile: a profile with one length
    + [cut('W2', 'Kitchen', 2, 'RE-3', 700.0, '27-4', bar=1)] * 4
    + [cut('W10', 'Hall', 2, 'RE-3', 700.0, '27-4', bar=1)] * 4
)
DATA = {'batch': 'Batch 1', 'quote': 'S00009', 'date': '2026-11-20',
        'state': 'Draft', 'bars': 3, 'feet': 42.0, 'stale': False,
        'cuts': CUTS}


def rows_of(sheet):
    return [[c.value for c in row] for row in sheet.iter_rows()]


def build(data):
    return openpyxl.load_workbook(io.BytesIO(x.build_cut_summary(data)))


book = build(DATA)
check('sheets', book.sheetnames == ['Summary', 'Cut list'], book.sheetnames)
summary, flat = book['Summary'], book['Cut list']

for sheet in (summary, flat):
    top = rows_of(sheet)[:6]
    check('top rows %s' % sheet.title, [r[0] for r in top] == [
        'Batch', 'Quote', 'Date', 'Plan state', 'Bars bought', 'Feet bought'],
        top)
    check('top values %s' % sheet.title,
          [r[1] for r in top] == ['Batch 1', 'S00009', '2026-11-20', 'Draft',
                                  3, 42.0], top)
    check('no stale note when current %s' % sheet.title,
          all(x.STALE_NOTE != r[0] for r in rows_of(sheet)))

# -- blocks ---------------------------------------------------------------
blocks = x.blocks_of(CUTS)
check('two blocks', len(blocks) == 2, len(blocks))
frame, second = blocks
check('frame lengths longest first',
      [mm for _t, mm in frame['lengths']] == [1500.0, 1200.0, 900.0],
      frame['lengths'])
check('a profile with one length has one column',
      len(second['lengths']) == 1, second['lengths'])
check('natural order W1, W2, W10',
      [r['window'] for r in frame['rows']] == ['W1', 'W2', 'W10'],
      [r['window'] for r in frame['rows']])
check('a window with two profiles is in both blocks',
      'W2' in [r['window'] for r in frame['rows']]
      and 'W2' in [r['window'] for r in second['rows']])
pieces = sum(1 for _ in CUTS)
check('block pieces add up to the cuts',
      sum(b['totals']['pieces'] for b in blocks) == pieces,
      [b['totals']['pieces'] for b in blocks])
feet = sum(c['length_mm'] for c in CUTS) / x.MM_PER_FOOT
check('block feet add up to the cuts',
      abs(sum(b['totals']['feet'] for b in blocks) - feet) < 1e-9)

# two lengths that read the same in the workshop (3657.6 and 3658 mm) are one column
same = x.blocks_of([cut('W1', 'A', 9, 'X', 3657.6, '144'),
                    cut('W1', 'A', 9, 'X', 3658.0, '144'),
                    cut('W2', 'B', 9, 'X', 3658.0, '144')])[0]
check('same workshop text is one column',
      len(same['lengths']) == 1 and same['lengths'][0] == ('144', '3657.6-3658'),
      same['lengths'])
check('and its counts and feet are the real ones',
      same['totals']['counts'] == {'144': 3}
      and abs(same['totals']['feet'] - (3657.6 + 3658 + 3658) / x.MM_PER_FOOT) < 1e-9,
      same['totals'])

# -- what is in the sheet -------------------------------------------------
cells = rows_of(summary)
titles = [i for i, r in enumerate(cells) if r[0] in ('RE-8 / 1.2 / Natural',
                                                      'RE-3 / 1.2 / Natural')]
check('block titles', len(titles) == 2, titles)
head = cells[titles[0] + 1]
check('header: workshop text of each length',
      head[2:5] == ['59-0', '47-2', '35-3'] and head[5:7] == ['Pieces', 'Feet'],
      head)
under = cells[titles[0] + 2]
check('exact mm under the text', under[2:5] == [1500.0, 1200.0, 900.0], under)
first = cells[titles[0] + 3]
check('rows start with window and location, naturally sorted',
      [first[0], cells[titles[0] + 4][0], cells[titles[0] + 5][0]]
      == ['W1', 'W2', 'W10'], [first[0], cells[titles[0] + 4][0]])
check('zero is blank', first[3] is None and first[4] is None, first)
check('row ends with total pieces and feet',
      first[5] == 1 and abs(first[6] - round(1500 / x.MM_PER_FOOT, 1)) < 1e-9,
      first)
w2 = cells[titles[0] + 4]
check('W2 counts', w2[2:5] == [None, 2, 2] and w2[5] == 4, w2)
total = cells[titles[0] + 6]
check('block ends with column totals',
      total[0] == 'Total' and total[2:5] == [1, 4, 2] and total[5] == 7, total)

one = cells[titles[1] + 1]
check('the one-length profile has a single length column',
      one[2] == '27-4' and one[3] == 'Pieces', one)

# -- the Cut list ---------------------------------------------------------
flat_rows = rows_of(flat)
header_row = next(i for i, r in enumerate(flat_rows) if r[0] == 'Window')
check('cut list header', flat_rows[header_row] == x.CUT_HEADERS)
body = [r for r in flat_rows[header_row + 1:] if r[0]]
check('one row per cut', len(body) == len(CUTS), len(body))
check('typed flag', sum(1 for r in body if r[12] == 'typed') == 2,
      [r[12] for r in body])
check('mm is a number', all(isinstance(r[8], (int, float)) for r in body))
check('autofilter',
      flat.auto_filter.ref and flat.auto_filter.ref.startswith('A%d' % (header_row + 1)),
      flat.auto_filter.ref)
check('frozen header', flat.freeze_panes == 'A%d' % (header_row + 2),
      flat.freeze_panes)

# -- stale ----------------------------------------------------------------
stale = build(dict(DATA, stale=True))
for sheet in stale.worksheets:
    notes = [c for row in sheet.iter_rows() for c in row if c.value == x.STALE_NOTE]
    check('stale note on %s' % sheet.title, len(notes) == 1, len(notes))
    check('stale note is red on %s' % sheet.title,
          notes and notes[0].font.color is not None
          and notes[0].font.color.rgb.endswith('C00000'))

# -- an empty batch -------------------------------------------------------
try:
    x.build_cut_summary(dict(DATA, cuts=[]))
    check('empty batch refused', False, 'no error')
except ValueError as error:
    check('empty batch message', 'no cuts' in str(error), str(error))

check('file name', x.file_name('S 00001', 2, '2026-11-20')
      == 'cut_summary_S_00001_batch2_2026-11-20.xlsx')
check('natural key', sorted(['W10', 'W2', 'W1', 'w3'], key=x.natural_key)
      == ['W1', 'W2', 'w3', 'W10'])

if failures:
    print("FAIL: %d problem(s)" % len(failures))
    for failure in failures:
        print("  -", failure)
    sys.exit(1)
print("cut summary workbook: all checks passed")
