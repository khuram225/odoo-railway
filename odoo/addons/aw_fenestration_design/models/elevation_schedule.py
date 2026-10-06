# -*- coding: utf-8 -*-
"""Data for the Elevation Schedule report (client approval sheet).

Everything the template shows is worked out here, so the template is
only layout: wkhtmltopdf has no flexbox, and logic in QWeb is harder to
check than logic in Python.
"""
import re

from odoo import models

PER_PAGE = 6          # three across, two down


def _natural_key(design):
    """W1, W2 ... W10 in that order: digits compare as numbers, so W10
    does not sort before W2. A ref with no digits sorts after the
    numbered ones."""
    name = (design.name or '').lower()
    parts = re.split(r'(\d+)', name)
    return (0 if re.search(r'\d', name) else 1,
            [(0, int(p)) if p.isdigit() else (1, p) for p in parts],
            design.id)


class AwDesign(models.Model):
    _inherit = 'aw.design'

    def _schedule_dimension(self, mm):
        """'1219.20 mm (4' 0")': millimetres to two decimals, then feet
        and inches, whatever the unit setting is."""
        self.ensure_one()
        total_in = (mm or 0.0) / 25.4
        feet = int(total_in // 12)
        return '%.2f mm (%s\' %s")' % (
            mm or 0.0, feet, self._trim(total_in - feet * 12))

    def _schedule_glass(self):
        """Glass grouped by panel number: '(1) 6+10+8 Clear Tempered;
        (2,3) 6+10+6 Clear Tempered'. Panels sharing a glass are listed
        together, in the order their first panel appears."""
        self.ensure_one()
        groups = {}
        for panel in self._report_panels():
            if panel['glass']:
                groups.setdefault(panel['glass'], []).append(
                    panel['panel_no'])
        return '; '.join(
            '(%s) %s' % (','.join(str(n) for n in numbers), glass)
            for glass, numbers in groups.items())


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _aw_elevation_schedule_pages(self):
        """The order's active windows in Design Ref order, six to a page."""
        self.ensure_one()
        designs = self.aw_design_ids.filtered('active').sorted(
            key=_natural_key)
        return [designs[i:i + PER_PAGE]
                for i in range(0, len(designs), PER_PAGE)]
