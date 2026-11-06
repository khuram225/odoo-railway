#!/usr/bin/env python3
"""The Excel rate template is built the way the plan says, or this fails.

Runs the REAL `build_template` out of
aw_fenestration_core/models/rate_xlsx.py (Odoo-free for exactly this) and reads
the bytes back with openpyxl, a second library, so a mistake in how it was
written shows up as something Excel would see:

  * a blank file is a header row only and nothing in it is locked;
  * a prefilled file is protected WITHOUT a password, with sort and filter
    allowed, identity cells locked, price cells open, the key column hidden;
  * the "New items" block is 30 open rows under a heading;
  * the Code column is text, so 1-2 and 07 stay what they were typed;
  * the Info sheet carries vendor, kind, date, list id, version, download time;
  * glass has its own three columns.

Skips loudly (skipping) when openpyxl or xlsxwriter is missing; CI installs both
and runs this --strict, so a skip there is a failure.
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
          / 'aw_fenestration_core' / 'models' / 'rate_xlsx.py')
spec = importlib.util.spec_from_file_location('aw_rate_xlsx', MODULE)
x = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x)

failures = []


def check(label, ok, detail=''):
    if not ok:
        failures.append("%s %s" % (label, detail))


def load(data):
    return openpyxl.load_workbook(io.BytesIO(data))


INFO = {'vendor': 'Chawla', 'vendor_id': 7, 'date': '2026-11-01',
        'list_id': 42, 'content': 'With current rates',
        'series': 'DG.SERIES', 'downloaded': '2026-11-06 09:30'}

CHAWLA = ['DULL', 'BRO', 'H.23', 'WOOD']
PREMIUM = ['NATURAL', 'BRN', 'SHARA']

PROFILE_ROWS = [
    {'key': 'p:1:5', 'cells': ['RE-8', 'Standard', 'DG.SERIES',
                               610.5, 640.0, None, 700.25]},
    # codes Excel would turn into dates or drop a zero from
    {'key': 'p:2:5', 'cells': ['1-2', '1.6MM', 'DG.SERIES',
                               500.0, None, None, None]},
    {'key': 'p:3:6', 'cells': ['07', 'Std', 'DG.SERIES',
                               None, None, None, 99.0]},
]

# ------------------------------------------------------------------ blank
blank = load(x.build_template(
    dict(INFO, content='Blank template', series=''), 'profile', CHAWLA))
check('sheets', blank.sheetnames == ['Rates', 'Info'], blank.sheetnames)
ws = blank['Rates']
check('blank header', [c.value for c in ws[1]] ==
      ['Code', 'Thickness', 'Series'] + CHAWLA, [c.value for c in ws[1]])
check('blank has no data rows', ws.max_row == 1, ws.max_row)
check('blank is not protected', not ws.protection.sheet)
check('blank header cells unlocked',
      all(not c.protection.locked for c in ws[1]))
check('blank has no key column', ws.max_column == 3 + len(CHAWLA),
      ws.max_column)

# --------------------------------------------------------------- prefilled
for name, finishes in (('Chawla', CHAWLA), ('Premium', PREMIUM)):
    rows = [dict(r, cells=r['cells'][:3] + r['cells'][3:3 + len(finishes)]
                 + [None] * max(0, len(finishes) - len(r['cells'][3:])))
            for r in PROFILE_ROWS]
    book = load(x.build_template(
        dict(INFO, vendor=name), 'profile', finishes, rows, prefilled=True))
    ws = book['Rates']
    headers = [c.value for c in ws[1]]
    check(name + ' header', headers == ['Code', 'Thickness', 'Series']
          + finishes + ['Key'], headers)
    key_letter = openpyxl.utils.get_column_letter(len(headers))
    check(name + ' key column hidden',
          ws.column_dimensions[key_letter].hidden)
    check(name + ' protected, no password',
          ws.protection.sheet and not ws.protection.password)
    check(name + ' sort allowed', ws.protection.sort is False
          or ws.protection.sort == 0, ws.protection.sort)
    check(name + ' filter allowed', ws.protection.autoFilter is False
          or ws.protection.autoFilter == 0, ws.protection.autoFilter)
    # a code is kept exactly as typed, as text
    codes = [ws.cell(row=i, column=1).value for i in (2, 3, 4)]
    check(name + ' codes kept', codes == ['RE-8', '1-2', '07'], codes)
    check(name + ' codes are text', all(
        ws.cell(row=i, column=1).data_type == 's'
        and ws.cell(row=i, column=1).number_format == '@'
        for i in (2, 3, 4)))
    check(name + ' keys', [ws.cell(row=i, column=len(headers)).value
                           for i in (2, 3, 4)] == ['p:1:5', 'p:2:5', 'p:3:6'])
    # identity cells locked, price cells open
    for i in (2, 3, 4):
        check(name + ' identity locked row %s' % i, all(
            ws.cell(row=i, column=c).protection.locked for c in (1, 2, 3)))
        check(name + ' prices open row %s' % i, all(
            not ws.cell(row=i, column=c).protection.locked
            for c in range(4, 4 + len(finishes))))
    check(name + ' header locked', all(c.protection.locked for c in ws[1]))
    # prices are numbers; an empty price stays empty, never 0
    check(name + ' price number', ws.cell(row=2, column=4).value == 610.5)
    check(name + ' empty price stays empty',
          ws.cell(row=3, column=5).value is None)
    # New items block: heading then 30 open rows
    heading = 5
    check(name + ' New items heading',
          ws.cell(row=heading, column=1).value == 'New items',
          ws.cell(row=heading, column=1).value)
    check(name + ' New items heading locked',
          ws.cell(row=heading, column=1).protection.locked)
    check(name + ' 30 open rows', ws.max_row == heading + 30, ws.max_row)
    check(name + ' New items rows are open', all(
        not ws.cell(row=r, column=c).protection.locked
        for r in range(heading + 1, heading + 31)
        for c in range(1, 4 + len(finishes))))
    check(name + ' New items code is text', all(
        ws.cell(row=r, column=1).number_format == '@'
        for r in range(heading + 1, heading + 31)))
    # Info
    info = {a.value: b.value for a, b in book['Info'].iter_rows(
        min_col=1, max_col=2) if a.value}
    for label, want in (('Vendor', name), ('Vendor id', '7'),
                        ('Kind', 'Profiles'), ('Effective date', '2026-11-01'),
                        ('List id', '42'), ('Template version', '1'),
                        ('Downloaded', '2026-11-06 09:30'),
                        ('Content', 'With current rates'),
                        ('Series', 'DG.SERIES')):
        check(name + ' info ' + label, info.get(label) == want,
              (label, info.get(label)))
    check(name + ' info mentions Enable Editing', any(
        'Enable Editing' in (b.value or '')
        for a, b in book['Info'].iter_rows(min_col=1, max_col=2)))

# -------------------------------------------------------------------- glass
glass_rows = [
    {'key': 'g:3:6', 'cells': ['Clear', 6, 100.0]},
    {'key': 'g:4:5', 'cells': ['Ref. Grey', 5, 231.88]},
]
book = load(x.build_template(
    dict(INFO, vendor='Ghani', series=''), 'glass', (), glass_rows,
    prefilled=True))
ws = book['Rates']
check('glass header', [c.value for c in ws[1]] ==
      ['Glass type', 'Thickness (mm)', 'Price per sqft', 'Key'],
      [c.value for c in ws[1]])
check('glass row', [ws.cell(row=2, column=c).value for c in (1, 2, 3)] ==
      ['Clear', 6, 100.0])
check('glass identity locked, price open',
      ws.cell(row=2, column=1).protection.locked
      and ws.cell(row=2, column=2).protection.locked
      and not ws.cell(row=2, column=3).protection.locked)
check('glass kind in Info', {a.value: b.value for a, b in book['Info'].iter_rows(
    min_col=1, max_col=2) if a.value}.get('Kind') == 'Glass')
glass_blank = load(x.build_template(
    dict(INFO, content='Blank template'), 'glass'))
check('glass blank', [c.value for c in glass_blank['Rates'][1]] ==
      ['Glass type', 'Thickness (mm)', 'Price per sqft']
      and glass_blank['Rates'].max_row == 1)

if failures:
    print("FAIL: the rate template is not built as planned:")
    for line in failures:
        print("  -", line)
    sys.exit(1)
print("pass: blank and prefilled profile files (Chawla-like, Premium-like) "
      "and glass files are built as planned (protection, hidden key, text "
      "codes, New items block, Info sheet)")
