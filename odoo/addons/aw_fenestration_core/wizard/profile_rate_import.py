# -*- coding: utf-8 -*-
"""Import a melted price list as a new set of profile rates.

Takes the same CSV `scripts/rebuild_melt_and_import.py` produces:

    profile_code, thickness_raw, thickness_normalized, finish,
    price_pkr, effective_from, uom_note

Two things worth knowing about the join. Profile templates carry **no
default_code** -- the profile_code IS the template's `name` (see
data/chawla_profiles_data.xml), so that is what this matches on.
And the thickness is read from `thickness_normalized`, the column the
product import itself used, rather than re-normalising `thickness_raw`
here; a second copy of that mapping would eventually disagree with the
first and silently mis-key rates.

The summary is the point of the wizard. An import that quietly succeeds
with half the codes unmatched is worse than one that fails, because the
missing ones only surface later as a quote with no price.
"""
import base64
import csv
import io
from collections import defaultdict
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError

REQUIRED_COLUMNS = {
    'profile_code', 'thickness_normalized', 'finish', 'price_pkr',
}


class AwProfileRateImport(models.TransientModel):
    _name = 'aw.profile.rate.import'
    _description = 'Import Fenestration Profile Price List'

    file_data = fields.Binary(string='Price List (CSV)', required=True)
    file_name = fields.Char()
    date_from = fields.Date(
        string='Effective From', required=True,
        default=fields.Date.context_today,
        help="Rates are never edited in place. This date is what the "
             "lookup compares against a quote's order date.")
    vendor_id = fields.Many2one('res.partner', string='Vendor')

    state = fields.Selection([
        ('choose', 'Choose'),
        ('done', 'Done'),
    ], default='choose')
    summary = fields.Html(readonly=True)

    def _read_rows(self):
        self.ensure_one()
        try:
            text = base64.b64decode(self.file_data).decode('utf-8-sig')
        except (ValueError, UnicodeDecodeError) as error:
            raise UserError(_(
                "That file could not be read as UTF-8 CSV: %s", error))
        reader = csv.DictReader(io.StringIO(text))
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise UserError(_(
                "This does not look like a melted price list. Missing "
                "column(s): %s", ', '.join(sorted(missing))))
        return list(reader)

    def action_import(self):
        self.ensure_one()
        rows = self._read_rows()

        templates = {
            template.name: template
            for template in self.env['product.template'].search(
                [('name', '!=', False)])
        }
        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_finish')
        values_by_name = defaultdict(dict)
        for value in self.env['product.attribute.value'].search(
                [('attribute_id', 'in',
                  (thickness_attr.id, finish_attr.id))]):
            values_by_name[value.attribute_id.id][value.name] = value

        # Every rate already in force on this date, in ONE query. The
        # obvious version calls _rate_for per row, which on the real
        # Chawla list (3473 rows) is roughly ten thousand queries and
        # long enough to hit a worker timeout the first time anyone
        # uses this. A dict lookup is also exact, since the comparison
        # only ever needs the same key.
        # Same vendor only, matching the chain key: another supplier's
        # price for the same profile is a different chain, and reporting
        # it as "changed" would be comparing two unrelated numbers.
        previous_by_key = {}
        for rate in self.env['aw.profile.rate'].search(
            [('date_from', '<=', self.date_from),
             ('vendor_id', '=', self.vendor_id.id or False)],
            order='date_from asc, id asc',
        ):
            previous_by_key[(
                rate.product_tmpl_id.id,
                rate.thickness_id.id,
                rate.finish_id.id,
            )] = rate.price

        to_create = []
        unknown_codes = set()
        unknown_values = set()
        no_price = set()
        changes = []
        seen_templates = set()

        for row in rows:
            code = (row.get('profile_code') or '').strip()
            if not code:
                continue
            template = templates.get(code)
            if not template:
                unknown_codes.add(code)
                continue
            seen_templates.add(template.id)

            raw_price = (row.get('price_pkr') or '').strip()
            if not raw_price:
                # The melt records a profile with no price at all as a
                # blank row so the combination is not lost. Keep that
                # visible rather than treating it as zero.
                no_price.add(code)
                continue
            try:
                price = float(raw_price)
            except ValueError:
                no_price.add(code)
                continue

            thickness = False
            thickness_name = (row.get('thickness_normalized') or '').strip()
            if thickness_name:
                thickness = values_by_name[thickness_attr.id].get(
                    thickness_name)
                if not thickness:
                    unknown_values.add('Thickness: %s' % thickness_name)
                    continue
            finish = False
            finish_name = (row.get('finish') or '').strip()
            if finish_name:
                finish = values_by_name[finish_attr.id].get(finish_name)
                if not finish:
                    unknown_values.add('Finish: %s' % finish_name)
                    continue

            key = (template.id,
                   thickness.id if thickness else False,
                   finish.id if finish else False)
            previous = previous_by_key.get(key)
            if previous is not None and abs(previous - price) > 1e-9:
                changes.append((
                    code, thickness_name or '—', finish_name or '—',
                    previous, price))

            to_create.append({
                'product_tmpl_id': template.id,
                'thickness_id': key[1],
                'finish_id': key[2],
                'price': price,
                'date_from': self.date_from,
                'vendor_id': self.vendor_id.id or False,
                'source_note': self.file_name or '',
            })

        created = self.env['aw.profile.rate'].create(to_create) \
            if to_create else self.env['aw.profile.rate']

        # Rates this import closed. create() rebuilt the chains, so the
        # ones it retired now end the day before this list starts.
        closed = 0
        if created:
            closed = self.env['aw.profile.rate'].search_count([
                ('id', 'not in', created.ids),
                ('date_to', '=', self.date_from - timedelta(days=1)),
                ('has_successor', '=', True),
            ])

        # A new price list is exactly when costs go stale, so refresh
        # them here rather than leaving someone to remember the button.
        if created:
            variants = self.env['product.product'].search([
                ('product_tmpl_id', 'in',
                 created.mapped('product_tmpl_id').ids),
            ])
            # Returns (updated, blocked); the blocked ones are left
            # to the costing method, not forced.
            variants._aw_sync_cost_from_rate()

        # Profiles in the catalogue that this list never priced. These
        # are the ones that will quote at nothing, so they matter more
        # than the unmatched codes.
        priced_category = self.env.ref(
            'aw_fenestration_core.product_category_profiles',
            raise_if_not_found=False)
        catalogue_gap = []
        if priced_category:
            for template in self.env['product.template'].search([
                ('categ_id', 'child_of', priced_category.id),
            ]):
                if template.id not in seen_templates:
                    catalogue_gap.append(template.name)

        self.write({
            'state': 'done',
            'summary': self._build_summary(
                len(created), sorted(unknown_codes), sorted(catalogue_gap),
                sorted(no_price), changes, sorted(unknown_values), closed),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    def _build_summary(self, added, unknown_codes, catalogue_gap, no_price,
                       changes, unknown_values, closed):
        def block(title, items, limit=40):
            if not items:
                return ''
            shown = items[:limit]
            more = ('<li><em>… and %s more</em></li>'
                    % (len(items) - limit)) if len(items) > limit else ''
            return ('<h4>%s (%s)</h4><ul>%s%s</ul>' % (
                title, len(items),
                ''.join('<li>%s</li>' % item for item in shown), more))

        parts = ['<h3>%s rate(s) added</h3>' % added]
        if closed:
            parts.append(
                '<p>%s previous rate(s) closed on %s.</p>'
                % (closed, self.date_from - timedelta(days=1)))
        if changes:
            rows = ''.join(
                '<tr><td>%s</td><td>%s</td><td>%s</td>'
                '<td class="text-end">%.2f</td>'
                '<td class="text-end">%.2f</td></tr>'
                % (code, thickness, finish, old, new)
                for code, thickness, finish, old, new in changes[:40])
            parts.append(
                '<h4>Price changes vs the previous list (%s)</h4>'
                '<table class="table table-sm"><thead><tr>'
                '<th>Profile</th><th>Thickness</th><th>Finish</th>'
                '<th class="text-end">Was</th><th class="text-end">Now</th>'
                '</tr></thead><tbody>%s</tbody></table>' % (
                    len(changes), rows))
        parts.append(block('Codes in the file with no matching profile',
                           unknown_codes))
        parts.append(block('Profiles in the catalogue this list did not '
                           'price', catalogue_gap))
        parts.append(block('Rows with no price', no_price))
        parts.append(block('Thickness/finish values not in the catalogue',
                           unknown_values))
        return ''.join(part for part in parts if part)
