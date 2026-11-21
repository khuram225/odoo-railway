# -*- coding: utf-8 -*-
"""The cut summary of a cutting batch, as an .xlsx.

Free of Odoo imports, like rate_xlsx.py, so scripts/check_cut_summary_xlsx.py
runs this very code. It takes plain values in and returns the bytes.

Three sheets, all starting with the same few lines (batch, quote, date, plan
state, bars and feet bought, and a red note when the plan is stale):

  Summary   one block per profile (code, thickness, finish). Rows are the
            windows (natural order: W2 before W10) with their location,
            columns are the distinct cut lengths of that profile, longest
            first, written in the workshop style with the exact mm under it.
            A cell is a piece count, blank for zero; every row ends with its
            total pieces and total feet, every block with column totals.
            Window and location stay frozen, it prints landscape, the exact
            mm row is labelled "mm" in Location, and each block ends with a
            line of the bars used ("Bars: 23 x 18 ft", or the mix).
  Bars      one row per bar in the cutting sheet's own order and wording
            (piece references W19.4, remainder label): profile, "1 of 23",
            length (ft), the cuts in order, pieces, used, remainder. Marked
            "from an old plan" when the plan is stale.
  Cut list  flat, one row per cut, with the piece reference, autofilter and
            a frozen header.

A cut is one piece. A window's quantity is already in the plan (the BOM line
carries qty x the window's qty), so counting cuts is counting what is cut.

Input, `data`:
  batch, quote, date, state (text), bars (int), feet (float), stale (bool)
  cuts   one dict per cut: window, location, piece_ref, panel (int), code,
         thickness, finish, position, length_text (workshop style),
         length_mm, angle, bar_no, typed (bool), block (the profile block it
         belongs to, in the order the blocks should appear)
  bar_rows  one dict per bar, in the cutting sheet's order: block, code,
         thickness, finish, bar_no, bar_count, stock_mm, cuts [{ref, text,
         mm}], used_mm, used_text, remainder_mm, remainder_text, from_stock
"""
import io
import re

MM_PER_FOOT = 304.8
SUMMARY_SHEET = 'Summary'
BARS_SHEET = 'Bars'
CUTLIST_SHEET = 'Cut list'
STALE_NOTE = 'Plan is stale: regenerate before cutting'
BARS_STALE_NOTE = 'From an old plan: these bars are not the current cuts'
FEET_NOTE = ('Feet are rounded to 0.1 per row; each total adds the exact '
             'lengths, so a column of rounded rows can differ from it by '
             '0.1 or so.')
CUT_HEADERS = ['Window', 'Location', 'Piece', 'Panel', 'Profile',
               'Thickness', 'Finish', 'Position', 'Length (in)',
               'Length (mm)', 'Angle', 'Qty', 'Bar', 'Typed length']
BAR_HEADERS = ['Profile', 'Bar', 'Length (ft)', 'Cuts (in)', 'Pieces',
               'Used (in)', 'Remainder (in)', 'From stock']


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


def profile_title(item):
    """Code / thickness / finish, as the Summary block heading says it."""
    return ' / '.join(part for part in (
        item.get('code'), item.get('thickness'), item.get('finish')) if part)


def bars_line(bars):
    """'Bars: 23 x 18 ft', or the mix 'Bars: 3 x 20 ft + 2 x 18 ft'.

    Offcuts of earlier batches are not bought: they are told apart,
    '(+ 2 from stock)'."""
    bought, from_stock = {}, 0
    for bar in bars:
        if bar.get('from_stock'):
            from_stock += 1
        else:
            feet = round(bar['stock_mm'] / MM_PER_FOOT, 2)
            bought[feet] = bought.get(feet, 0) + 1
    mix = ' + '.join('%d x %g ft' % (count, feet)
                     for feet, count in sorted(bought.items(), reverse=True))
    if not mix:
        text = 'Bars: none bought'
    else:
        text = 'Bars: ' + mix
    if from_stock:
        text += ' (+ %d from stock)' % from_stock
    return text


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
        'note': book.add_format({'italic': True,
                                 'font_color': '#595959'}),
        'barsline': book.add_format({'bold': True,
                                     'font_color': '#1F4E78'}),
    }

    # -- Summary -----------------------------------------------------------
    sheet = book.add_worksheet(SUMMARY_SHEET)
    row = _top(book, sheet, data, formats)
    sheet.write_string(row - 1, 0, FEET_NOTE, formats['note'])
    row += 1
    bars_by_block = {}
    for bar in data.get('bar_rows') or []:
        bars_by_block.setdefault(bar['block'], []).append(bar)
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
        # The exact-mm row is labelled where the eye starts, in Location.
        sheet.write_blank(row + 1, 0, None, formats['headmm'])
        sheet.write_string(row + 1, 1, 'mm', formats['headmm'])
        sheet.write_blank(row + 1, 2 + count, None, formats['headmm'])
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
        row += 1
        if block['key'] in bars_by_block:
            sheet.write_string(row, 0, bars_line(bars_by_block[block['key']]),
                               formats['barsline'])
            row += 1
        row += 1
    sheet.set_column(0, 0, 11)
    sheet.set_column(1, 1, 24)
    sheet.set_column(2, max(widest, 3), 9)
    # A wide table stays readable: window and location stay put while the
    # lengths scroll, and it prints landscape on as many pages as it needs.
    sheet.freeze_panes(0, 2)
    sheet.set_landscape()
    sheet.set_paper(9)
    sheet.fit_to_pages(1, 0)

    # -- Bars --------------------------------------------------------------
    bars_sheet = book.add_worksheet(BARS_SHEET)
    row = _top(book, bars_sheet, data, formats)
    if data.get('stale'):
        bars_sheet.write_string(row - 1, 0, BARS_STALE_NOTE, formats['stale'])
        row += 1
    header_row = row
    for col, title in enumerate(BAR_HEADERS):
        bars_sheet.write_string(header_row, col, title, formats['head'])
    bars = list(data.get('bar_rows') or [])
    for offset, bar in enumerate(bars, start=1):
        line = header_row + offset
        bars_sheet.write_string(line, 0, profile_title(bar), formats['text'])
        bars_sheet.write_string(
            line, 1, '%d of %d' % (bar['bar_no'], bar['bar_count']),
            formats['text'])
        bars_sheet.write_number(
            line, 2, round(bar['stock_mm'] / MM_PER_FOOT, 2), formats['feet'])
        bars_sheet.write_string(line, 3, ' + '.join(
            '%s (%s)' % (c['text'], c['ref']) if c['ref'] else c['text']
            for c in bar['cuts']), formats['text'])
        bars_sheet.write_number(line, 4, len(bar['cuts']))
        bars_sheet.write_string(line, 5, bar['used_text'], formats['text'])
        bars_sheet.write_string(line, 6, bar['remainder_text'],
                                formats['text'])
        bars_sheet.write_string(line, 7, bar.get('from_stock') or '',
                                formats['text'])
    bars_sheet.autofilter(header_row, 0, header_row + len(bars),
                          len(BAR_HEADERS) - 1)
    bars_sheet.freeze_panes(header_row + 1, 0)
    bars_sheet.set_column(0, 0, 22)
    bars_sheet.set_column(1, 2, 10)
    bars_sheet.set_column(3, 3, 70)
    bars_sheet.set_column(4, 6, 14)
    bars_sheet.set_column(7, 7, 28)
    bars_sheet.set_landscape()
    bars_sheet.set_paper(9)
    bars_sheet.fit_to_pages(1, 0)
    bars_sheet.repeat_rows(header_row)

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
        flat.write_string(line, 2, cut.get('piece_ref') or '', formats['text'])
        flat.write_number(line, 3, cut['panel'] or 0)
        flat.write_string(line, 4, cut['code'], formats['text'])
        flat.write_string(line, 5, cut['thickness'], formats['text'])
        flat.write_string(line, 6, cut['finish'], formats['text'])
        flat.write_string(line, 7, cut['position'], formats['text'])
        flat.write_string(line, 8, cut['length_text'], formats['text'])
        flat.write_number(line, 9, round(cut['length_mm'], 1), formats['mm'])
        flat.write_string(line, 10, cut['angle'], formats['text'])
        flat.write_number(line, 11, 1)
        flat.write_number(line, 12, cut['bar_no'])
        flat.write_string(line, 13, 'typed' if cut['typed'] else '',
                          formats['text'])
    flat.autofilter(header_row, 0, header_row + len(ordered),
                    len(CUT_HEADERS) - 1)
    flat.freeze_panes(header_row + 1, 0)
    flat.set_column(0, 0, 10)
    flat.set_column(1, 1, 22)
    flat.set_column(2, 2, 10)
    flat.set_column(3, 3, 7)
    flat.set_column(4, 7, 16)
    flat.set_column(8, 13, 12)

    book.close()
    return buffer.getvalue()
