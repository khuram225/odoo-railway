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
import io

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
