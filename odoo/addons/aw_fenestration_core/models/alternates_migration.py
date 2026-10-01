# -*- coding: utf-8 -*-
"""Merge duplicate position lines into one line with alternates
(phase 7d, entry clean-up).

A position used to be able to carry several lines, distinguished by
`sequence` and named by an `option_label`. The alternatives live on ONE
line now, as products. This merges what is there.

**The requirement that shapes every decision below: a design already
quoted must come out with the same BOM and the same price.**

Two halves, in this order:

1. For each (spec, position) with more than one line, the LOWEST
   sequence becomes the single survivor and the others' products join
   its `alternate_product_ids`. The survivor is the line the explosion
   was already choosing -- `_section_lines_by_scope` took the lowest
   sequence -- so every design that had made no explicit choice keeps
   being built from exactly the same record.

2. A design that HAD made a choice stored the chosen LINE. Those lines
   are about to be deleted, so each design's choice is translated to
   the chosen line's PRODUCT first, while both still exist. A choice
   pointing at a line that is being merged away becomes that line's
   product, which is now an alternate of the survivor -- so the divider
   still cuts the same profile.

**Why it is called from the DESIGN module's data file, not Core's.**
It writes `aw.design.leaf.divider_product_id`, whose column is created
by the Design module. Core upgrades first, and at that point the new
column does not exist yet -- so running this during Core's own upgrade
would fail or silently skip. Design depends on Core, so by the time
Design loads, both schemas are there. `divider_line_id` is read in raw
SQL because the FIELD is gone from the model while the column survives:
Odoo never drops a column it stops using.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

MERGED_PARAM = 'aw_fenestration.position_alternates_merged'


class AwProfileSectionLine(models.Model):
    _inherit = 'aw.profile.section.line'

    def _column_exists(self, table, column):
        self.env.cr.execute("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = %s AND column_name = %s
        """, (table, column))
        return bool(self.env.cr.fetchone())

    @api.model
    def _migrate_max_span_to_products(self):
        """Lift max_span_mm off the lines onto the profiles.

        A profile mentioned by two lines with different ratings takes the
        HIGHER one. The lower was the more cautious guess, exceeding a
        limit is a warning rather than a block, and fill-only-if-empty
        means a rating already entered on the product wins over both.
        """
        if not self._column_exists('aw_profile_section_line', 'max_span_mm'):
            return 0
        self.env.cr.execute("""
            SELECT product_tmpl_id, MAX(max_span_mm)
              FROM aw_profile_section_line
             WHERE max_span_mm IS NOT NULL AND max_span_mm > 0
               AND product_tmpl_id IS NOT NULL
          GROUP BY product_tmpl_id
        """)
        moved = 0
        for template_id, limit in self.env.cr.fetchall():
            template = self.env['product.template'].browse(
                template_id).exists()
            if template and not template.aw_max_span_mm:
                template.aw_max_span_mm = limit
                moved += 1
        return moved

    @api.model
    def _chosen_line_ids(self, table):
        """{record id: chosen line id} out of the old column."""
        if not self._column_exists(table, 'divider_line_id'):
            return {}
        self.env.cr.execute("""
            SELECT id, divider_line_id FROM %s
             WHERE divider_line_id IS NOT NULL
        """ % table)
        return dict(self.env.cr.fetchall())

    @api.model
    def _migrate_position_alternates(self):
        """Merge duplicate lines, carrying designs' choices across."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(MERGED_PARAM):
            return False

        spans = self._migrate_max_span_to_products()

        # Read every stored choice BEFORE anything is deleted.
        chosen = {
            'aw.design.leaf': self._chosen_line_ids('aw_design_leaf'),
            'aw.design.row': self._chosen_line_ids('aw_design_row'),
        }

        groups = {}
        for line in self.search([('spec_id', '!=', False)]):
            groups.setdefault(
                (line.spec_id.id, line.position_id.id), []).append(line)

        # line id -> the product a design choosing it should now store.
        product_for_line = {}
        merged = 0
        for lines in groups.values():
            if len(lines) < 2:
                continue
            ordered = sorted(lines, key=lambda l: (l.sequence, l.id))
            survivor, losers = ordered[0], ordered[1:]
            for loser in losers:
                product_for_line[loser.id] = loser.product_tmpl_id
            survivor.alternate_product_ids = [(6, 0, [
                loser.product_tmpl_id.id for loser in losers
                if loser.product_tmpl_id
                and loser.product_tmpl_id != survivor.product_tmpl_id])]
            self.browse([loser.id for loser in losers]).unlink()
            merged += len(losers)

        # A choice that pointed at a SURVIVING line needs nothing written:
        # that line's product is the default, and empty means the default.
        # Only a choice whose line was merged away has to be translated.
        repointed = 0
        for model, by_record in chosen.items():
            for record_id, line_id in by_record.items():
                product = product_for_line.get(line_id)
                if not product:
                    continue
                record = self.env[model].browse(record_id).exists()
                if record:
                    record.divider_product_id = product
                    repointed += 1

        param.set_param(MERGED_PARAM, '1')
        _logger.info(
            "aw_fenestration_core phase 7d: %s duplicate position line(s) "
            "merged into alternates, %s design divider choice(s) "
            "re-pointed to a product, %s profile(s) given a max span",
            merged, repointed, spans)
        return True
