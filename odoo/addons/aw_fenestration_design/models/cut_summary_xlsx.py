# -*- coding: utf-8 -*-
"""The cut summary of a cutting batch, as an .xlsx.

Free of Odoo imports, like rate_xlsx.py, so scripts/check_cut_summary_xlsx.py
runs this very code. It takes plain values in and returns the bytes.

Two sheets, both starting with the same few lines (batch, quote, date, plan
state, bars and feet bought, and a red note when the plan is stale):

  Summary   one block per profile (code, thickness, finish). Rows are the
            windows (natural order: W2 before W10) with their location,
            columns are the distinct cut lengths of that profile, longest
            first, written in the workshop style with the exact mm under it.
            A cell is a piece count, blank for zero; every row ends with its
            total pieces and total feet, every block with column totals.
  Cut list  flat, one row per cut, with autofilter and a frozen header.

A cut is one piece. A window's quantity is already in the plan (the BOM line
carries qty x the window's qty), so counting cuts is counting what is cut.

Input, `data`:
  batch, quote, date, state (text), bars (int), feet (float), stale (bool)
  cuts   one dict per cut: window, location, panel (int), code, thickness,
         finish, position, length_text (workshop style), length_mm, angle,
         bar_no, typed (bool), block (the profile block it belongs to, in the
         order the blocks should appear)
"""
import io
import re

MM_PER_FOOT = 304.8
SUMMARY_SHEET = 'Summary'
CUTLIST_SHEET = 'Cut list'
STALE_NOTE = 'Plan is stale: regenerate before cutting'
CUT_HEADERS = ['Window', 'Location', 'Panel', 'Profile', 'Thickness',
               'Finish', 'Position', 'Length (in)', 'Length (mm)', 'Angle',
               'Qty', 'Bar', 'Typed length']


def need_library():
    try:
        import xlsxwriter
    except ImportError as error:  # pragma: no cover - image problem
        raise RuntimeError(
            "The Excel library (xlsxwriter) is not installed on this "
            "server, so the cut summary cannot be made. Ask whoever runs "
            "the server to install it.") from error
    return xlsxwriter


def natural_key(text):
    """W2 before W10: digits compare as numbers, the rest as lower case."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', text or '')]


def file_name(quote, batch_no, date):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', quote or 'quote').strip('_')
    return 'cut_summary_%s_batch%s_%s.xlsx' % (safe, batch_no, date)


def blocks_of(cuts):
    """The summary as data, in the order the blocks first appear.

    Returns a list of dicts: title, key, lengths (longest first, each a
    (text, mm) pair: the workshop text, and the exact mm under it), rows
    (window, location, counts by text, pieces, feet) and totals (counts by
    text, pieces, feet). Used by the sheet and by the check script, so what
    is written is what is tested.

    Lengths are told apart the way the workshop reads them: two cuts that
    show the same workshop text (3657.6 and 3658 mm both read 144) are one
    column, whose mm line shows both when they differ. Feet always add up the
    real lengths.
    """
    order, grouped = [], {}
    for cut in cuts:
        key = cut['block']
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(cut)
    blocks = []
    for key in order:
        members = grouped[key]
        first = members[0]
        spans = {}
        for cut in members:
            mm = round(cut['length_mm'], 1)
            low, high = spans.get(cut['length_text'], (mm, mm))
            spans[cut['length_text']] = (min(low, mm), max(high, mm))
        lengths = [(text, low if low == high else '%g-%g' % (low, high))
                   for text, (low, high) in sorted(
                       spans.items(), key=lambda item: -item[1][1])]
        windows = {}
        for cut in members:
            row = windows.setdefault(cut['window'], {
                'window': cut['window'], 'location': cut['location'],
                'counts': {}, 'mm': 0.0})
            text = cut['length_text']
            row['counts'][text] = row['counts'].get(text, 0) + 1
            row['mm'] += cut['length_mm']
        rows = []
        for ref in sorted(windows, key=natural_key):
            row = windows[ref]
            row['pieces'] = sum(row['counts'].values())
            row['feet'] = row['mm'] / MM_PER_FOOT
            rows.append(row)
        totals = {text: sum(r['counts'].get(text, 0) for r in rows)
                  for text, _mm in lengths}
        blocks.append({
            'key': key,
            'title': ' / '.join(
                part for part in (first['code'], first['thickness'],
                                  first['finish']) if part),
            'lengths': lengths,
            'rows': rows,
            'totals': {
                'counts': totals,
                'pieces': sum(totals.values()),
                'feet': sum(r['mm'] for r in rows) / MM_PER_FOOT,
            },
        })
    return blocks


def _top(book, sheet, data, formats):
    """The lines both sheets start with; returns the next free row."""
    rows = [('Batch', data['batch']), ('Quote', data['quote']),
            ('Date', data['date']), ('Plan state', data['state']),
            ('Bars bought', data['bars']),
            ('Feet bought', round(data['feet'], 1))]
    for index, (label, value) in enumerate(rows):
        sheet.write_string(index, 0, label, formats['label'])
        if isinstance(value, (int, float)):
            sheet.write_number(index, 1, value)
        else:
            sheet.write_string(index, 1, str(value), formats['text'])
    row = len(rows)
    if data.get('stale'):
        sheet.write_string(row, 0, STALE_NOTE, formats['stale'])
        row += 1
    return row + 1


def build_cut_summary(data):
    """The bytes of the .xlsx. Raises ValueError for a batch with no cuts."""
    cuts = list(data.get('cuts') or [])
    if not cuts:
        raise ValueError("This batch has no cuts to summarise. Generate the "
                         "plan first.")
    xlsxwriter = need_library()
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {'in_memory': True})
    formats = {
        'label': book.add_format({'bold': True}),
        'text': book.add_format({'num_format': '@'}),
        'stale': book.add_format({'bold': True, 'font_color': '#C00000'}),
        'title': book.add_format({'bold': True, 'font_size': 12,
                                  'bg_color': '#D9E1F2'}),
        'head': book.add_format({'bold': True, 'align': 'center',
                                 'bg_color': '#EDEDED', 'border': 1}),
        'headmm': book.add_format({'align': 'center', 'bg_color': '#EDEDED',
                                   'border': 1, 'num_format': '0.0',
                                   'font_color': '#595959'}),
        'cell': book.add_format({'align': 'center', 'border': 1}),
        'name': book.add_format({'border': 1, 'num_format': '@'}),
        'feet': book.add_format({'align': 'center', 'border': 1,
                                 'num_format': '0.0'}),
        'tot': book.add_format({'bold': True, 'align': 'center',
                                'border': 1, 'bg_color': '#E2EFDA'}),
        'totfeet': book.add_format({'bold': True, 'align': 'center',
                                    'border': 1, 'bg_color': '#E2EFDA',
                                    'num_format': '0.0'}),
        'totname': book.add_format({'bold': True, 'border': 1,
                                    'bg_color': '#E2EFDA'}),
        'mm': book.add_format({'num_format': '0.0'}),
    }

    # -- Summary -----------------------------------------------------------
    sheet = book.add_worksheet(SUMMARY_SHEET)
    row = _top(book, sheet, data, formats)
    widest = 0
    for block in blocks_of(cuts):
        count = len(block['lengths'])
        last = 2 + count + 1
        widest = max(widest, last)
        sheet.merge_range(row, 0, row, last, block['title'], formats['title'])
        row += 1
        sheet.write_string(row, 0, 'Window', formats['head'])
        sheet.write_string(row, 1, 'Location', formats['head'])
        for index, (text, mm) in enumerate(block['lengths']):
            sheet.write_string(row, 2 + index, text, formats['head'])
            if isinstance(mm, str):
                sheet.write_string(row + 1, 2 + index, mm, formats['headmm'])
            else:
                sheet.write_number(row + 1, 2 + index, mm, formats['headmm'])
        sheet.write_string(row, 2 + count, 'Pieces', formats['head'])
        sheet.write_string(row, 3 + count, 'Feet', formats['head'])
        sheet.write_blank(row + 1, 0, None, formats['headmm'])
        sheet.write_blank(row + 1, 1, None, formats['headmm'])
        sheet.write_string(row + 1, 2 + count, 'mm above', formats['headmm'])
        sheet.write_blank(row + 1, 3 + count, None, formats['headmm'])
        row += 2
        for entry in block['rows']:
            sheet.write_string(row, 0, entry['window'], formats['name'])
            sheet.write_string(row, 1, entry['location'], formats['name'])
            for index, (text, _mm) in enumerate(block['lengths']):
                number = entry['counts'].get(text, 0)
                if number:
                    sheet.write_number(row, 2 + index, number, formats['cell'])
                else:
                    sheet.write_blank(row, 2 + index, None, formats['cell'])
            sheet.write_number(row, 2 + count, entry['pieces'], formats['cell'])
            sheet.write_number(row, 3 + count, round(entry['feet'], 1),
                               formats['feet'])
            row += 1
        sheet.write_string(row, 0, 'Total', formats['totname'])
        sheet.write_blank(row, 1, None, formats['totname'])
        for index, (text, _mm) in enumerate(block['lengths']):
            sheet.write_number(row, 2 + index, block['totals']['counts'][text],
                               formats['tot'])
        sheet.write_number(row, 2 + count, block['totals']['pieces'],
                           formats['tot'])
        sheet.write_number(row, 3 + count, round(block['totals']['feet'], 1),
                           formats['totfeet'])
        row += 2
    sheet.set_column(0, 0, 11)
    sheet.set_column(1, 1, 24)
    sheet.set_column(2, max(widest, 3), 9)

    # -- Cut list ----------------------------------------------------------
    flat = book.add_worksheet(CUTLIST_SHEET)
    row = _top(book, flat, data, formats)
    header_row = row
    for col, title in enumerate(CUT_HEADERS):
        flat.write_string(header_row, col, title, formats['head'])
    ordered = sorted(cuts, key=lambda c: (
        natural_key(c['window']), c['code'], c['bar_no']))
    for offset, cut in enumerate(ordered, start=1):
        line = header_row + offset
        flat.write_string(line, 0, cut['window'], formats['text'])
        flat.write_string(line, 1, cut['location'], formats['text'])
        flat.write_number(line, 2, cut['panel'] or 0)
        flat.write_string(line, 3, cut['code'], formats['text'])
        flat.write_string(line, 4, cut['thickness'], formats['text'])
        flat.write_string(line, 5, cut['finish'], formats['text'])
        flat.write_string(line, 6, cut['position'], formats['text'])
        flat.write_string(line, 7, cut['length_text'], formats['text'])
        flat.write_number(line, 8, round(cut['length_mm'], 1), formats['mm'])
        flat.write_string(line, 9, cut['angle'], formats['text'])
        flat.write_number(line, 10, 1)
        flat.write_number(line, 11, cut['bar_no'])
        flat.write_string(line, 12, 'typed' if cut['typed'] else '',
                          formats['text'])
    flat.autofilter(header_row, 0, header_row + len(ordered),
                    len(CUT_HEADERS) - 1)
    flat.freeze_panes(header_row + 1, 0)
    flat.set_column(0, 0, 10)
    flat.set_column(1, 1, 22)
    flat.set_column(2, 2, 7)
    flat.set_column(3, 6, 16)
    flat.set_column(7, 12, 12)

    book.close()
    return buffer.getvalue()
