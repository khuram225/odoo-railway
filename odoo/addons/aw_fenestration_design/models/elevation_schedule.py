# -*- coding: utf-8 -*-
"""Data for the Elevation Schedule report (client approval sheet).

Everything the template shows is worked out here, so the template is
only layout: wkhtmltopdf has no flexbox, and logic in QWeb is harder to
check than logic in Python.
"""
import logging
import math
import re

from odoo import _, models

from odoo.addons.aw_fenestration_core.models.units import to_display

from . import elevation_print
from .natural import natural_key

_logger = logging.getLogger(__name__)

PER_PAGE = 6          # three across, two down

# All sizes below are CSS mm, which Odoo's PDFs print at 0.851 of their size
# (elevation_print.PAPER_SCALE): A4 landscape less 8 mm margins is 281 x 194 mm
# on the paper, 330 x 228 CSS mm to lay out.
PAGE_W_MM = 281.0 / elevation_print.PAPER_SCALE
PAGE_H_MM = 194.0 / elevation_print.PAPER_SCALE

# The Elevation Schedule: six to a page, each cell the drawing on the LEFT and
# the details on the right. Cells are as tall as the page allows (the header
# takes what the logo needs), labels at 6 pt on the paper (6.40: the next step
# the print engine can draw, see PRINT_STEP_PT).
LOGO_FACTOR = 2.0                 # of the size it printed at before (chosen after
SCHEDULE_LOGO_H_MM = 16.0 * LOGO_FACTOR      # looking at 1x, 1.5x and 2x)
SCHEDULE_LOGO_W_MM = 60.0 * LOGO_FACTOR
SCHEDULE_LABEL_PT = 6.0
SCHEDULE_DRAW_FRACTION = 0.56     # of the cell's width
SCHEDULE_DETAIL_PX = 10.0         # CSS px = 6.4 pt on the paper, like the labels (8 px was 5.1)
SCHEDULE_TITLE_MM = 6.0           # "View From Inside"

# The one-window Elevation Sheet: the drawing on the left (62% of the width), the
# details on the right, labels at 10 pt on the paper.
SHEET_LOGO_H_MM = 28.0 * LOGO_FACTOR
SHEET_LOGO_W_MM = 90.0 * LOGO_FACTOR
SHEET_LABEL_PT = 10.0
SHEET_DETAIL_PX = 17.0
SHEET_BOX_MM = (168.0, 138.0)
SHEET_DETAIL_W_MM = PAGE_W_MM * 0.38 - 8.0


def _natural_key(design):
    """W1, W2 ... W10 in that order (see natural.natural_key)."""
    return natural_key(design.name, design.id)


NOT_CHOSEN = 'not chosen'


class AwDesign(models.Model):
    _inherit = 'aw.design'

    def _schedule_dimension(self, mm):
        """'48 in (1219.2 mm)': inches by the one display rule first,
        then millimetres to one decimal, whatever the unit setting is."""
        self.ensure_one()
        return '%s in (%.1f mm)' % (to_display(mm), mm or 0.0)

    def _schedule_area(self):
        """'28.33 sqft · 2.63 sqm': width x height of the window, whatever
        the unit setting. sqft is square inches / 144, sqm is m2; two
        decimals, so the two figures agree to the digit a customer can
        check with a calculator."""
        self.ensure_one()
        width, height = self.width_mm or 0.0, self.height_mm or 0.0
        sqft = (width / 25.4) * (height / 25.4) / 144.0
        sqm = width * height / 1000000.0
        return '%.2f sqft · %.2f sqm' % (sqft, sqm)

    def _elevation_print(self, box_mm, label_pt):
        """The drawing redrawn for a printed box, or False.

        From the stored SVG, with the dimension labels at `label_pt` ON THE
        PAPER (not in CSS terms: the page prints at 0.85 of its CSS size, see
        elevation_print.PAPER_SCALE; the stored PNG is made at screen size and
        cannot be rescaled),
        and as a vector: a fifth of the bytes of the PNG, so a document with
        many windows is no longer made of many large bitmaps. False when
        there is no stored SVG or it cannot be read; the report then prints
        the stored PNG as it always did.
        """
        self.ensure_one()
        if not self.elevation_svg:
            return False
        try:
            out = elevation_print.print_for_paper(
                self.elevation_svg, box_mm, label_pt, min_paper_pt=label_pt - 2)
        except Exception:                          # a drawing must never stop a report
            _logger.warning("elevation %s: the stored drawing could not be "
                            "redrawn; the PNG is printed", self.display_name,
                            exc_info=True)
            return False
        out['src'] = elevation_print.data_uri(out['svg'])
        return out

    def _elevation_sheet_print(self):
        """The drawing for the one-window Elevation Sheet: labels at 10 pt."""
        self.ensure_one()
        return self._elevation_print(SHEET_BOX_MM, SHEET_LABEL_PT)

    def _schedule_glass(self):
        """Glass grouped by panel number: '(1) 6+10+8 Clear Tempered;
        (2,3) 6+10+6 Clear Tempered'. Panels sharing a glass are listed
        together, in the order their first panel appears.

        A panel with no glass product chosen says "not chosen" (it is a gap
        in the quote, not "no glass"); when no panel has one the text is just
        "not chosen"."""
        self.ensure_one()
        groups = {}
        for panel in self._report_panels():
            groups.setdefault(panel['glass'] or NOT_CHOSEN, []).append(
                panel['panel_no'])
        if list(groups) == [NOT_CHOSEN]:
            return NOT_CHOSEN
        return '; '.join(
            '(%s) %s' % (','.join(str(n) for n in numbers), glass)
            for glass, numbers in groups.items())

    def _schedule_georgian(self):
        """The Georgian bars, grouped by identical spec: [('P1, P2, P3',
        'Georgian bars, rectangular, 4 x 2')]. Nothing for a panel without
        bars. All the data there is: the pattern and, for a rectangular one,
        its rows x columns; no width, profile or spacing is stored, so none is
        printed."""
        self.ensure_one()
        groups = {}
        for leaf in self._all_panels().sorted(lambda l: l.panel_no or 0):
            pattern = leaf.grid_pattern_id
            if not pattern:
                continue
            spec = pattern.name or pattern.code or ''
            if pattern.kind == 'rect' and leaf.grid_rows and leaf.grid_cols:
                spec = '%s, %d x %d' % (spec, leaf.grid_rows, leaf.grid_cols)
            groups.setdefault(spec, []).append(leaf.panel_no or 0)
        return [(', '.join('P%d' % n for n in numbers), spec)
                for spec, numbers in groups.items()]

    def _schedule_georgian_lines(self):
        """'P1, P2, P3: Georgian bars, rectangular, 4 x 2', one per group."""
        self.ensure_one()
        return ['%s: %s' % pair for pair in self._schedule_georgian()]

    # ------------------------------------------------------------------
    # the details block: as tall as the window's frame
    # ------------------------------------------------------------------
    def _elevation_detail_rows(self):
        """[(label, text)] of the details beside a drawing, in print order: the
        ONE list both the Elevation Sheet and every Elevation Schedule cell print
        (same fields, order and wording; only the size of the text differs).
        The Georgian bars row is there only when the window has bars."""
        self.ensure_one()
        rows = [
            (_('Design Ref'), self.name or ''),
            (_('Qty'), '%s' % self.qty),
            (_('Location'), self.location or '-'),
            (_('W'), self._schedule_dimension(self.width_mm)),
            (_('H'), self._schedule_dimension(self.height_mm)),
            (_('Area'), self._schedule_area()),
            (_('Glass'), self._schedule_glass()),
            (_('Finish'), self.finish_id.aw_doc_name()
             if self.finish_id else '-'),
        ]
        bars = self._schedule_georgian()
        if bars:
            # the label already says "Georgian bars"
            prefix = 'Georgian bars, '
            rows.append((_('Georgian bars'), '; '.join(
                '%s: %s' % (panels, spec[len(prefix):]
                            if spec.startswith(prefix) else spec)
                for panels, spec in bars)))
        return rows

    def _elevation_details(self, frame_top_mm, frame_h_mm, font_px, width_mm,
                           label_fraction=0.38):
        """The details block, laid out to be exactly as tall as the window frame.

        Its top edge is on the top of the frame and its bottom edge on the
        bottom, the rows spread evenly between: each row gets a share of the
        frame's height in proportion to the lines its text needs (estimated
        from the width and the size of the text), so a row of one line and a
        row of three have the same room per line. {'top_mm', 'height_mm',
        'rows': [{'label', 'text', 'lines', 'height_mm'}]}. With no frame
        (a drawing that could not be read) the heights are None and the block
        is as tall as its text.
        """
        self.ensure_one()
        char_mm = font_px * 0.2646 * 0.62          # an average character
        label_w = width_mm * label_fraction
        value_w = width_mm - label_w
        rows = []
        for label, text in self._elevation_detail_rows():
            per_line = max(1, int(value_w / char_mm * 0.9))
            lines = max(1, int(math.ceil(len(text) / float(per_line))))
            label_per_line = max(1, int(label_w / char_mm * 0.9))
            lines = max(lines, int(math.ceil(len(label) / float(label_per_line))))
            rows.append({'label': label, 'text': text, 'lines': lines})
        total = float(sum(r['lines'] for r in rows)) or 1.0
        for row in rows:
            row['height_mm'] = (frame_h_mm * row['lines'] / total
                                if frame_h_mm else None)
        return {'top_mm': frame_top_mm or 0.0, 'height_mm': frame_h_mm,
                'font_px': font_px, 'label_fraction': label_fraction * 100.0,
                'rows': rows}

    def _schedule_cell(self, layout):
        """One cell of the Elevation Schedule: the drawing and the details."""
        self.ensure_one()
        printed = self._elevation_print(layout['draw_box'], SCHEDULE_LABEL_PT)
        frame = printed and printed.get('frame_h_mm')
        return {
            'printed': printed,
            'details': self._elevation_details(
                printed and printed.get('frame_top_mm'), frame,
                SCHEDULE_DETAIL_PX, layout['detail_w']),
        }

    def _sheet_logo_mm(self):
        """(max height, max width) of the logo on the Elevation Sheet, CSS mm."""
        return (SHEET_LOGO_H_MM, SHEET_LOGO_W_MM)

    def _sheet_cell(self):
        """The one-window Elevation Sheet's drawing and details."""
        self.ensure_one()
        printed = self._elevation_sheet_print()
        frame = printed and printed.get('frame_h_mm')
        return {
            'printed': printed,
            'details': self._elevation_details(
                printed and printed.get('frame_top_mm'), frame,
                SHEET_DETAIL_PX, SHEET_DETAIL_W_MM),
        }


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _aw_schedule_layout(self):
        """The schedule's geometry in CSS mm: the logo, the header, the cells (as
        tall as the page allows, so a bigger logo takes room from them and not
        from the page), the drawing's box on the left and the width of the
        details on the right."""
        header = SCHEDULE_LOGO_H_MM + 3.0
        # 4 mm narrower than the page: at 1 mm wkhtmltopdf found the content a hair too
        # wide and shrank the whole page, and the labels printed 6.37 pt instead of 6.40
        page_w = PAGE_W_MM - 4.0
        cell_w = page_w / 3.0
        # slack under the grid: a page a millimetre too tall prints as two
        cell_h = (PAGE_H_MM - header - 12.0) / 2.0
        pad = 2.0
        inner_w = cell_w - 2 * pad - 0.5
        inner_h = cell_h - 2 * pad - 0.5
        return {
            'logo_h': SCHEDULE_LOGO_H_MM, 'logo_w': SCHEDULE_LOGO_W_MM,
            'header_h': header, 'cell_h': cell_h, 'pad': pad,
            'page_w': page_w, 'cell_w': cell_w,
            'title_h': SCHEDULE_TITLE_MM,
            'draw_w_pct': SCHEDULE_DRAW_FRACTION * 100.0,
            'draw_box': (inner_w * SCHEDULE_DRAW_FRACTION,
                         inner_h - SCHEDULE_TITLE_MM),
            'detail_w': inner_w * (1 - SCHEDULE_DRAW_FRACTION) - 1.5,
        }

    def _aw_elevation_designs(self):
        """The order's active windows in Design Ref order (W2 before W10)."""
        self.ensure_one()
        return self.aw_design_ids.filtered('active').sorted(key=_natural_key)

    def _aw_elevation_schedule_pages(self):
        """The order's active windows in Design Ref order, six to a page."""
        self.ensure_one()
        designs = self._aw_elevation_designs()
        return [designs[i:i + PER_PAGE]
                for i in range(0, len(designs), PER_PAGE)]
