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
  * glass has its own three columns;
  * READING it back (Upload): two changed prices, a code Excel turned into a
    date or a number, a price stored as text, with a thousands separator or a
    decimal comma, a typed 0 and a blank, a file from another vendor, kind,
    date, list or template version, a hidden key that disagrees with its code,
    an extra sheet, a hidden row, merged cells, a file re-saved by another
    program, and any real Excel-saved file in tests/data.

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

# ====================================================================== reading
# Upload: the same file comes back, edited the ways people really edit it.
import datetime

EXPECTED = {'vendor': 'Chawla', 'vendor_id': '7', 'kind': 'Profiles',
            'date': '2026-11-01', 'list_id': '42', 'version': '1'}
GLASS_EXPECTED = dict(EXPECTED, vendor='Ghani', kind='Glass')

KEYS = {
    'p:1:5': {'code': 'RE-8', 'thickness': 'Standard'},
    'p:2:5': {'code': '1-2', 'thickness': '1.6MM'},
    'p:3:6': {'code': '07', 'thickness': 'Std'},
}
GLASS_KEYS = {'g:3:6': {'code': 'Clear', 'thickness': 6},
              'g:4:5': {'code': 'Ref. Grey', 'thickness': 5}}


def fresh(finishes=CHAWLA, rows=None):
    return x.build_template(INFO, 'profile', finishes,
                            rows or PROFILE_ROWS, prefilled=True)


def edit(data, change):
    book = openpyxl.load_workbook(io.BytesIO(data))
    change(book)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def read(data, finishes=CHAWLA, expected=EXPECTED, kind='profile',
         lookup=KEYS):
    return x.read_template(
        data, kind, finishes, expected, lambda k: lookup.get(k))


def said(result, *words):
    text = ' '.join(result['errors'] + result['problems']).lower()
    return all(w.lower() in text for w in words)


# a good file, untouched, then with two prices changed, for both vendors
for name, finishes in (('Chawla', CHAWLA), ('Premium', PREMIUM)):
    rows = [dict(r, cells=r['cells'][:3] + (r['cells'][3:] + [None] * 4)[
        :len(finishes)]) for r in PROFILE_ROWS]
    data = fresh(finishes, rows)
    got = read(data, finishes)
    check(name + ' reads clean', not got['errors'] and not got['problems'],
          got['errors'] + got['problems'])
    check(name + ' three rows', len(got['rows']) == 3, len(got['rows']))
    changed = edit(data, lambda b: (
        b['Rates'].cell(row=2, column=4, value=612.0),
        b['Rates'].cell(row=3, column=4, value=505.5)))
    got = read(changed, finishes)
    check(name + ' two prices changed read back',
          got['rows'][0]['prices'][0] == 612.0
          and got['rows'][1]['prices'][0] == 505.5, got['rows'][:2])
    check(name + ' keys and codes kept',
          [r['key'] for r in got['rows']] == ['p:1:5', 'p:2:5', 'p:3:6']
          and [r['code'] for r in got['rows']] == ['RE-8', '1-2', '07'])
    check(name + ' blank prices counted, never 0',
          got['rows'][0]['prices'][2] is None and got['blank_cells'] > 0
          and all(p != 0 for r in got['rows'] for p in r['prices']))

data = fresh()

# a file saved by another program: rewritten wholesale by openpyxl (new
# styles, shared strings, no protection) stands in for LibreOffice / Sheets
resaved = edit(data, lambda b: b['Rates'].protection.disable())
got = read(resaved)
check('re-saved file reads the same', not got['errors'] and not got['problems']
      and [r['code'] for r in got['rows']] == ['RE-8', '1-2', '07'],
      got['errors'] + got['problems'])
# the same file with no hidden key column at all (a program that drops it)
nokey = edit(data, lambda b: b['Rates'].delete_cols(8))
got = read(nokey, lookup={})
check('without the key column the codes still read',
      not got['errors'] and not got['problems'] and len(got['rows']) == 3,
      got['errors'] + got['problems'])

# Excel turned a code into a date
as_date = edit(data, lambda b: b['Rates'].cell(
    row=3, column=1, value=datetime.datetime(2026, 2, 1)))
got = read(as_date)
check('code turned into a date', said(got, 'row 3', 'date'), got['problems'])
as_datetext = edit(data, lambda b: b['Rates'].cell(
    row=3, column=1, value='2-Jan'))
check('code that is date text', said(read(as_datetext), 'looks like a date'))
lost_zero = edit(data, lambda b: b['Rates'].cell(row=4, column=1, value=7))
check('code that became a number', said(read(lost_zero), 'row 4', 'number'))

# prices that are not numbers
for label, value, words in (
        ('price as text', '610.5', ('stored as text',)),
        ('thousands separator', '1,234.50', ('thousands separator',)),
        ('decimal comma', '12,5', ('decimal comma',)),
        ('words', 'ask', ('not a number',)),
        ('typed zero', 0, ('more than 0', 'row 2')),
        ('negative', -5, ('more than 0',)),
        ('a date', datetime.datetime(2026, 1, 2), ('date',)),
        ('excel error', '#N/A', ('error',))):
    bad = edit(data, lambda b, v=value: b['Rates'].cell(
        row=2, column=4, value=v))
    got = read(bad)
    check(label, said(got, *words) and not got['errors'], got['problems'])
def clear(book):
    book['Rates'].cell(row=2, column=4).value = None


blank = edit(data, clear)
got = read(blank)
check('blank price is not a problem', not got['problems']
      and got['rows'][0]['prices'][0] is None)

# not this list's file
for label, change, words in (
        ('other vendor', {'Vendor id': '8', 'Vendor': 'Premium'},
         ('made for', 'chawla', 'premium')),
        ('other kind', {'Kind': 'Glass'}, ('made for', 'glass')),
        ('other date', {'Effective date': '2026-10-01'},
         ('made for', '2026-10-01')),
        ('other list, same vendor kind date', {'List id': '41'},
         ('another list', '41', '42')),
        ('older version', {'Template version': '0'}, ('version 0',))):
    def swap(book, change=change):
        for row in book['Info'].iter_rows(min_col=1, max_col=2):
            if row[0].value in change:
                row[1].value = change[row[0].value]
    got = read(edit(data, swap))
    check(label + ' is refused', got['errors'] and not got['rows']
          and said(got, *words), got['errors'])

# the hidden key disagrees with the code beside it
moved = edit(data, lambda b: b['Rates'].cell(row=2, column=1, value='RE-9'))
check('key disagrees with code', said(read(moved), 'row 2', 'hidden key'),
      read(moved)['problems'])
thick = edit(data, lambda b: b['Rates'].cell(row=2, column=2, value='Thin'))
check('key disagrees with thickness', said(read(thick), 'hidden key'))
dupe = edit(data, lambda b: b['Rates'].cell(row=3, column=8, value='p:1:5'))
check('same key twice', said(read(dupe), 'repeats row 2'), read(dupe)['problems'])
check('a key that matches nothing', said(read(data, lookup={}), 'matches nothing'))

# things reported, not stopped
def extras(book):
    book.create_sheet('Scratch')
    book['Rates'].row_dimensions[3].hidden = True
    book['Rates'].merge_cells('A20:B20')
got = read(edit(data, extras))
check('extra sheet, hidden row and merged cells are reported, file still read',
      not got['errors'] and not got['problems'] and len(got['rows']) == 3
      and any('Scratch' in n for n in got['notes'])
      and any('hidden row' in n for n in got['notes'])
      and any('Merged' in n for n in got['notes']), got['notes'])
check('hidden row was still read', got['rows'][1]['code'] == '1-2')

# New items typed in the open block
def typed(book):
    sheet = book['Rates']
    for row in range(1, sheet.max_row + 1):
        if sheet.cell(row=row, column=1).value == 'New items':
            sheet.cell(row=row + 1, column=1, value='RE-99')
            sheet.cell(row=row + 1, column=2, value='Standard')
            sheet.cell(row=row + 1, column=3, value='DG.SERIES')
            sheet.cell(row=row + 1, column=4, value=700.0)
got = read(edit(data, typed))
new = [r for r in got['rows'] if r['new']]
check('a New items row is read', len(new) == 1 and new[0]['code'] == 'RE-99'
      and new[0]['prices'][0] == 700.0 and not got['problems'], got['problems'])
check('empty New items rows are not rows', len(got['rows']) == 4,
      len(got['rows']))

# structure
renamed = edit(data, lambda b: b['Rates'].cell(row=1, column=2, value='Thick'))
check('renamed header', said(read(renamed), 'column B', 'thick'))
check('not an xlsx', 'not an Excel' in ' '.join(
    x.read_template(b'hello', 'profile', CHAWLA)['errors']))
nosheet = edit(data, lambda b: b.remove(b['Info']))
check('no Info sheet', 'sheets' in ' '.join(read(nosheet)['errors']))

# glass
gdata = x.build_template(dict(INFO, vendor='Ghani'), 'glass', (), glass_rows,
                         prefilled=True)
got = read(gdata, (), GLASS_EXPECTED, 'glass', GLASS_KEYS)
check('glass reads clean', not got['errors'] and not got['problems']
      and [(r['code'], r['thickness'], r['prices']) for r in got['rows']]
      == [('Clear', 6.0, [100.0]), ('Ref. Grey', 5.0, [231.88])],
      got['errors'] + got['problems'])
gtext = edit(gdata, lambda b: b['Rates'].cell(row=2, column=2, value='6mm'))
check('glass thickness typed with mm', read(
    gtext, (), GLASS_EXPECTED, 'glass', GLASS_KEYS)['rows'][0]['thickness']
    == 6.0)
gmoved = edit(gdata, lambda b: b['Rates'].cell(row=2, column=2, value=8))
check('glass key disagrees with thickness', said(read(
    gmoved, (), GLASS_EXPECTED, 'glass', GLASS_KEYS), 'hidden key'))

# a real file saved by Excel, when one has been added to the fixtures
FIXTURE = (Path(__file__).resolve().parent.parent / 'odoo' / 'addons'
           / 'aw_fenestration_design' / 'tests' / 'data')
for path in sorted(FIXTURE.glob('*.xlsx')) if FIXTURE.is_dir() else []:
    raw = path.read_bytes()
    book = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    info = {a.value: b.value for a, b in book['Info'].iter_rows(
        min_col=1, max_col=2) if a.value}
    kind = 'glass' if info.get('Kind') == 'Glass' else 'profile'
    headers = [c.value for c in book['Rates'][1]]
    finish = [h for h in headers[3:] if h and h != 'Key'] \
        if kind == 'profile' else ()
    want = {'vendor': info.get('Vendor'), 'vendor_id': info.get('Vendor id'),
            'kind': info.get('Kind'), 'date': info.get('Effective date'),
            'list_id': info.get('List id'), 'version': '1'}
    got = x.read_template(raw, kind, finish, want)
    check('fixture %s reads' % path.name, not got['errors']
          and not got['problems'] and got['rows'],
          got['errors'] + got['problems'][:3])
    print("fixture %s: %d row(s), %d blank price(s), notes: %s" % (
        path.name, len(got['rows']), got['blank_cells'], got['notes']))


if failures:
    print("FAIL: the rate template is not built as planned:")
    for line in failures:
        print("  -", line)
    sys.exit(1)
print("pass: blank and prefilled profile files (Chawla-like, Premium-like) "
      "and glass files are built as planned, and read back the way people "
      "really edit them")
