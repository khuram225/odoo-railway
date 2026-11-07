# -*- coding: utf-8 -*-
"""The Excel rate template: what Download writes and Upload will read.

Free of Odoo imports, like rate_paste.py, so scripts/check_rate_xlsx.py runs
this very code. It takes plain values in and returns the bytes of an .xlsx.

Two sheets:

  Rates  the table. Row 1 is the header. A profile file has Code, Thickness,
         Series, then one column per finish under the vendor's OWN header,
         and (prefilled files only) a hidden Key column at the far right. A
         glass file has Glass type, Thickness (mm), Price per sqft.
  Info   vendor, kind, effective date, list id, template version, when it was
         downloaded. Upload refuses a file whose Info differs from the list.

A prefilled file protects the sheet WITHOUT a password (it stops accidents,
not people): code, thickness, series, header and key cells are locked, price
cells are open, and so are the ~30 "New items" rows at the bottom, for codes
that are not in the rates in force. Sort and filter stay allowed. A blank
file is fully unlocked. The Code column is text format, so Excel cannot turn
a code like 1-2 into a date. Dates on the Info sheet are written as text for
the same reason.
"""
import datetime as _dt
import io
import math
import re

TEMPLATE_VERSION = 1
NEW_ITEMS = 'New items'
NEW_ITEM_ROWS = 30
RATES_SHEET = 'Rates'
INFO_SHEET = 'Info'

# Info sheet labels. Upload reads them back by these exact words.
INFO_VENDOR = 'Vendor'
INFO_VENDOR_ID = 'Vendor id'
INFO_KIND = 'Kind'
INFO_DATE = 'Effective date'
INFO_LIST_ID = 'List id'
INFO_VERSION = 'Template version'
INFO_DOWNLOADED = 'Downloaded'
INFO_CONTENT = 'Content'
INFO_SERIES = 'Series'

PROFILE_FIXED = ('Code', 'Thickness', 'Series')
GLASS_HEADERS = ('Glass type', 'Thickness (mm)', 'Price per sqft')
KEY_HEADER = 'Key'

ENABLE_EDITING = ("Open the file in Excel and press Enable Editing before "
                  "you type.")


def need_libraries():
    """The two libraries, or a plain message when the image lacks them."""
    try:
        import xlsxwriter
    except ImportError as error:  # pragma: no cover - image problem
        raise RuntimeError(
            "The Excel library (xlsxwriter) is not installed on this "
            "server, so the template cannot be made. Ask whoever runs the "
            "server to install it.") from error
    return xlsxwriter


def headers_for(kind, finish_headers):
    if kind == 'glass':
        return list(GLASS_HEADERS)
    return list(PROFILE_FIXED) + [h or '' for h in finish_headers]


def build_template(info, kind, finish_headers=(), rows=(), prefilled=False):
    """The bytes of the .xlsx.

    info            dict: vendor, vendor_id, date (text), list_id, content,
                    series, downloaded (text)
    kind            'profile' or 'glass'
    finish_headers  the vendor's own header for each finish column
    rows            prefilled rows, each a dict: key, cells (a list in header
                    order: code, thickness, series, prices... or glass type,
                    thickness, price)
    prefilled       True protects the sheet and adds the key column and the
                    New items rows; False is a header row only, unlocked.
    """
    xlsxwriter = need_libraries()
    headers = headers_for(kind, finish_headers)
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {'in_memory': True})
    sheet = book.add_worksheet(RATES_SHEET)
    about = book.add_worksheet(INFO_SHEET)

    head = book.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1,
                            'locked': True})
    text_locked = book.add_format({'num_format': '@', 'locked': True})
    text_open = book.add_format({'num_format': '@', 'locked': False})
    number_locked = book.add_format({'locked': True})
    price_open = book.add_format({'num_format': '#,##0.00', 'locked': False,
                                  'bg_color': '#FFFBE6'})
    band = book.add_format({'bold': True, 'bg_color': '#E2EFDA',
                            'num_format': '@', 'locked': True})
    label = book.add_format({'bold': True, 'locked': True})
    plain = book.add_format({'num_format': '@', 'locked': True})

    fixed = 1 if kind == 'glass' else len(PROFILE_FIXED)
    # Which columns hold prices: every finish column; for glass, the last.
    price_from = 2 if kind == 'glass' else len(PROFILE_FIXED)
    locked_text = text_locked if prefilled else text_open

    for col, title in enumerate(headers):
        sheet.write_string(0, col, title, head if prefilled else book.add_format(
            {'bold': True, 'bg_color': '#D9E1F2', 'border': 1,
             'locked': False}))
    key_col = len(headers)
    if prefilled:
        sheet.write_string(0, key_col, KEY_HEADER, head)

    def write_cell(row, col, value, is_price, locked=True):
        if is_price:
            if value in (None, ''):
                sheet.write_blank(row, col, None, price_open)
            else:
                sheet.write_number(row, col, float(value), price_open)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            sheet.write_number(row, col, value, number_locked if locked
                               else price_open)
        else:
            sheet.write_string(row, col, '' if value is None else str(value),
                               locked_text)

    row_no = 1
    for entry in rows:
        cells = entry['cells']
        for col, value in enumerate(cells):
            write_cell(row_no, col, value, col >= price_from)
        if prefilled:
            sheet.write_string(row_no, key_col, entry.get('key') or '',
                               text_locked)
        row_no += 1

    if prefilled:
        # a heading row, then rows open for typing
        sheet.write_string(row_no, 0, NEW_ITEMS, band)
        for col in range(1, len(headers)):
            sheet.write_blank(row_no, col, None, band)
        row_no += 1
        for _ in range(NEW_ITEM_ROWS):
            for col in range(len(headers)):
                if col >= price_from:
                    sheet.write_blank(row_no, col, None, price_open)
                else:
                    sheet.write_blank(row_no, col, None, text_open)
            row_no += 1
        sheet.set_column(key_col, key_col, None, None, {'hidden': True})

    sheet.set_column(0, 0, 18, text_open if not prefilled else None)
    sheet.set_column(1, max(fixed, 1), 14)
    if kind == 'profile':
        sheet.set_column(len(PROFILE_FIXED), max(len(headers) - 1,
                                                 len(PROFILE_FIXED)), 12)
    sheet.freeze_panes(1, 1)
    sheet.autofilter(0, 0, max(row_no - 1, 0), len(headers) - 1)
    if prefilled:
        # No password. Sort and filter stay allowed.
        sheet.protect('', {'sort': True, 'autofilter': True,
                           'format_columns': True})

    # Info: label in column A, value in column B, all text.
    lines = [
        (INFO_VENDOR, info.get('vendor')),
        (INFO_VENDOR_ID, str(info.get('vendor_id') or '')),
        (INFO_KIND, 'Glass' if kind == 'glass' else 'Profiles'),
        (INFO_DATE, info.get('date')),
        (INFO_LIST_ID, str(info.get('list_id') or '')),
        (INFO_VERSION, str(TEMPLATE_VERSION)),
        (INFO_DOWNLOADED, info.get('downloaded')),
        (INFO_CONTENT, info.get('content')),
        (INFO_SERIES, info.get('series') or ''),
        ('', ''),
        ('', ENABLE_EDITING),
        ('', "Type prices only. Leave a price empty to leave that rate as "
             "it is; an empty cell is never read as 0."),
    ]
    for index, (name, value) in enumerate(lines):
        about.write_string(index, 0, name or '', label)
        about.write_string(index, 1, value or '', plain)
    about.set_column(0, 0, 20)
    about.set_column(1, 1, 60)
    about.protect('')
    sheet.activate()
    book.close()
    return buffer.getvalue()


# ====================================================================== reading
# Upload reads ONLY the Rates sheet (and Info, to know whose file it is). It
# never guesses: a cell that could be read two ways is a problem in plain words
# and the whole file is refused, exactly as a bad paste is.
_MONTHS = 'jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec'
_DATE_TEXT = re.compile(
    r'^(\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?'
    r'|\d{1,2}[-/ .](%s)[a-z]*([-/ .]\d{2,4})?'
    r'|(%s)[a-z]*[-/ .]\d{1,2}([-/ .]\d{2,4})?'
    r'|\d{1,2}/\d{1,2}/\d{2,4})$' % (_MONTHS, _MONTHS), re.I)
_THOUSANDS = re.compile(r'^\d{1,3}(,\d{3})+(\.\d+)?$')
_COMMA_DECIMAL = re.compile(r'^\d+,\d{1,2}$')
_PLAIN_NUMBER = re.compile(r'^\d+(\.\d+)?$')
_MM = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*$', re.I)


def norm(text):
    """A code or a thickness compared without case, spaces, hyphens, dots."""
    return re.sub(r'[\s\-_.]+', '', str(text if text is not None else '')
                  .upper())


def _is_date(value):
    return isinstance(value, (_dt.datetime, _dt.date, _dt.time, _dt.timedelta))


def _clean(value):
    return value.strip() if isinstance(value, str) else value


def read_price(value):
    """(price, blank, problem). A blank is 'leave unchanged' and is never 0."""
    value = _clean(value)
    if value is None or value == '' or value == '-':
        return None, True, None
    if isinstance(value, bool):
        return None, False, "is not a number"
    if _is_date(value):
        return None, False, ("was read by Excel as a date; "
                             "type the price as a plain number")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value)
                                         or math.isinf(value)):
            return None, False, "is not a number"
        if value <= 0:
            return None, False, (
                "is %s. A price must be more than 0; leave the cell empty "
                "to keep the current rate" % ('%g' % value))
        return float(value), False, None
    text = str(value)
    if text.startswith('#'):
        return None, False, "is an Excel error (%s)" % text
    if _THOUSANDS.match(text):
        return None, False, (
            "'%s' has a thousands separator and was kept as text; type it "
            "without the comma (%s)" % (text, text.replace(',', '')))
    if _COMMA_DECIMAL.match(text):
        return None, False, (
            "'%s' uses a decimal comma; type it with a point (%s)"
            % (text, text.replace(',', '.')))
    if _PLAIN_NUMBER.match(text):
        return None, False, (
            "'%s' is stored as text, not a number; format the cell as "
            "Number and type it again" % text)
    return None, False, "'%s' is not a number" % text


def _code_problem(value):
    if _is_date(value):
        return ("was changed to a date by Excel; format the Code column as "
                "Text and type the code again")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ("was read as the number %g; a code that is only digits may "
                "have lost a leading zero. Format the Code column as Text "
                "and type it again" % value)
    if isinstance(value, str) and _DATE_TEXT.match(value.strip()):
        return ("'%s' looks like a date, not a code; type the code again "
                "with the column formatted as Text" % value.strip())
    return None


def info_problem(info, expected):
    """Why a file does not belong to this list, in plain words, or ''.

    info and expected: vendor, vendor_id, kind ('Glass'/'Profiles'), date,
    list_id, version -- all as text."""
    if not info.get(INFO_LIST_ID) and not info.get(INFO_VENDOR_ID):
        return ("This is not a rate template from this system (its Info "
                "sheet is missing). Download one from the list.")
    if str(info.get(INFO_VERSION) or '') != str(expected['version']):
        return ("This file was made with template version %s; the current "
                "version is %s. Download a new template from this list."
                % (info.get(INFO_VERSION) or '?', expected['version']))
    same = (str(info.get(INFO_VENDOR_ID) or '') == str(expected['vendor_id'])
            and (info.get(INFO_KIND) or '') == expected['kind']
            and (info.get(INFO_DATE) or '') == expected['date'])
    if not same:
        return ("This file was made for %s, %s, %s. This list is for %s, %s, "
                "%s." % (info.get(INFO_VENDOR) or '?', info.get(INFO_KIND)
                         or '?', info.get(INFO_DATE) or '?',
                         expected['vendor'], expected['kind'],
                         expected['date']))
    if str(info.get(INFO_LIST_ID) or '') != str(expected['list_id']):
        return ("This file was made for another list (number %s; this one "
                "is %s), even though the vendor, kind and date are the same. "
                "Download the template from this list."
                % (info.get(INFO_LIST_ID) or '?', expected['list_id']))
    return ''


def _letter(index):
    letters = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def read_template(data, kind, finish_headers=(), expected=None, lookup=None):
    """Read an uploaded .xlsx.

    expected  the list's own Info (see info_problem); None skips that check
    lookup    key -> {'code': text, 'thickness': text or number} for the
              hidden key column, or None when the key names nothing

    Returns {'errors': [...]  stop, nothing read;
             'info': {...}, 'rows': [...], 'problems': [...]  stop too;
             'notes': [...]  worth telling, not stopping;
             'blank_cells': n, 'empty_rows': n}
    Each row: row (Excel number), key, code, thickness, series, prices (None
    for a blank), new (typed under New items), problems.
    """
    result = {'errors': [], 'info': {}, 'rows': [], 'problems': [],
              'notes': [], 'blank_cells': 0, 'empty_rows': 0}
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - image problem
        result['errors'].append(
            "The Excel library (openpyxl) is not installed on this server.")
        return result
    try:
        book = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception:  # noqa: BLE001 - zip, xml and format errors alike
        result['errors'].append(
            "This is not an Excel (.xlsx) file, or it is damaged. Open the "
            "template in Excel and save it again as .xlsx.")
        return result
    if RATES_SHEET not in book.sheetnames or INFO_SHEET not in book.sheetnames:
        result['errors'].append(
            "The file has no '%s' and '%s' sheets, so it is not the template "
            "from this system. Download one from the list." % (
                RATES_SHEET, INFO_SHEET))
        return result
    about = book[INFO_SHEET]
    info = {}
    for row in about.iter_rows(min_col=1, max_col=2, values_only=True):
        if row[0]:
            info[str(row[0]).strip()] = ('' if row[1] is None
                                         else str(row[1]).strip())
    result['info'] = info
    if expected is not None:
        problem = info_problem(info, expected)
        if problem:
            result['errors'].append(problem)
            return result

    sheet = book[RATES_SHEET]
    headers = headers_for(kind, finish_headers)
    first = [c.value for c in next(sheet.iter_rows(min_row=1, max_row=1))]
    for index, want in enumerate(headers):
        got = first[index] if index < len(first) else None
        if norm(got) != norm(want):
            result['errors'].append(
                "Column %s is headed '%s' but the template has '%s'. Do not "
                "rename, move or delete columns; download a fresh template."
                % (_letter(index), got if got is not None else '', want))
            return result
    key_index = len(headers) if (len(first) > len(headers)
                                 and norm(first[len(headers)])
                                 == norm(KEY_HEADER)) else None

    # things worth saying, never stopping
    others = [n for n in book.sheetnames if n not in (RATES_SHEET, INFO_SHEET)]
    if others:
        result['notes'].append(
            "Other sheets were ignored: %s." % ', '.join(others))
    hidden_sheets = [n for n in book.sheetnames
                     if book[n].sheet_state != 'visible']
    if hidden_sheets:
        result['notes'].append(
            "Hidden sheets: %s (only Rates is read)." % ', '.join(
                hidden_sheets))
    merged = [str(r) for r in sheet.merged_cells.ranges]
    if merged:
        result['notes'].append(
            "Merged cells on the Rates sheet (%s): only the top left cell of "
            "each holds a value, so check those rows." % ', '.join(merged[:5])
            + (' ...' if len(merged) > 5 else ''))

    price_from = 2 if kind == 'glass' else len(PROFILE_FIXED)
    seen_keys = {}
    new_section = False
    hidden_rows = 0
    width = len(headers) + (1 if key_index is not None else 0)
    for number, cells in enumerate(
            sheet.iter_rows(min_row=2, max_col=max(width, 1),
                            values_only=True), start=2):
        cells = list(cells) + [None] * (width - len(cells))
        identity = [_clean(c) for c in cells[:price_from]]
        if sheet.row_dimensions[number].hidden:
            hidden_rows += 1
        key = _clean(cells[key_index]) if key_index is not None else None
        prices = cells[price_from:len(headers)]
        if not any(c not in (None, '') for c in cells[:width]):
            result['empty_rows'] += 1
            continue
        if (isinstance(identity[0], str)
                and identity[0].strip().lower() == NEW_ITEMS.lower()
                and not key
                and not any(c not in (None, '') for c in cells[1:width])):
            new_section = True
            continue
        row = {'row': number, 'key': key or '', 'new': new_section,
               'problems': [], 'series': ''}
        def fail(text, row=row):
            row['problems'].append(text)

        # identity
        code = cells[0]
        bad = _code_problem(code)
        row['code'] = '' if code is None else str(code).strip()
        label = row['code'] or 'row %d' % number
        if bad:
            fail("Code %s" % bad)
        elif not row['code']:
            fail("has no %s" % ('glass type' if kind == 'glass' else 'code'))
        thickness = cells[1]
        if kind == 'glass':
            if _is_date(thickness):
                fail("Thickness (mm) was changed to a date by Excel")
                row['thickness'] = None
            elif isinstance(thickness, (int, float)) \
                    and not isinstance(thickness, bool):
                row['thickness'] = float(thickness)
            else:
                match = _MM.match(str(thickness or ''))
                row['thickness'] = float(match.group(1)) if match else None
            if row['thickness'] is None and not any(
                    'Thickness' in p for p in row['problems']):
                fail("needs one thickness in mm, like 6 (got '%s')"
                     % ('' if thickness is None else thickness))
            elif row['thickness'] is not None and row['thickness'] <= 0:
                fail("needs a thickness above 0")
        else:
            if _is_date(thickness):
                fail("Thickness was changed to a date by Excel")
                row['thickness'] = ''
            elif isinstance(thickness, float) and thickness.is_integer():
                row['thickness'] = '%d' % thickness
            else:
                row['thickness'] = '' if thickness is None else str(
                    thickness).strip()
            row['series'] = '' if cells[2] is None else str(cells[2]).strip()

        # the hidden key must agree with the code and thickness beside it
        if key:
            if key in seen_keys:
                fail("repeats row %d (same hidden key); delete one of them"
                     % seen_keys[key])
            else:
                seen_keys[key] = number
            known = lookup(key) if lookup else None
            if lookup and not known:
                fail("has a hidden key that matches nothing here any more; "
                     "download a fresh template")
            elif known:
                code_ok = norm(known['code']) == norm(row['code'])
                if kind == 'glass':
                    thick_ok = (row['thickness'] is not None and abs(
                        float(known['thickness']) - row['thickness']) < 1e-9)
                else:
                    thick_ok = norm(known['thickness']) == norm(
                        row['thickness'])
                if not (code_ok and thick_ok):
                    fail("says %s %s in its hidden key but the cells read "
                         "%s %s. The row was edited, or a sort or paste "
                         "moved the code away from its key; download a "
                         "fresh template" % (
                             known['code'], known['thickness'],
                             row['code'], row['thickness']))

        # prices
        values = []
        for offset, cell in enumerate(prices):
            price, blank, why = read_price(cell)
            if why:
                fail("%s %s" % (headers[price_from + offset], why))
            if blank:
                result['blank_cells'] += 1
            values.append(price)
        row['prices'] = values
        row['label'] = label
        result['rows'].append(row)
        for text in row['problems']:
            result['problems'].append("Row %d (%s): %s" % (number, label, text))

    if hidden_rows:
        result['notes'].append(
            "%d hidden row(s) on the Rates sheet were read like the rest."
            % hidden_rows)
    return result
