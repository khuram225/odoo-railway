# -*- coding: utf-8 -*-
"""A finish has several names.

A finish is still one Finish attribute value, and a rate, a variant and a
window still point at that value. What a vendor calls it (DULL, natural,
SHARA) is a NAME of the finish, added when that vendor's layout column is
mapped to it. Names are shown joined with " / " with the order vendor's
own first; customer documents show the finish's own name, or the optional
customer name. There are no groups and no per-vendor values, so costing
looks up exactly what it always did.
"""
import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MIGRATED_PARAM = 'aw_fenestration.finish_names_migrated'

# Premium's own headers and the finish each one names. Nothing here is
# linked across vendors on a guess: the user confirmed each line.
PREMIUM_HEADERS = {
    'DULL': 'Natural',
    'RAL P.C': 'H23 PC RAL',
    'H.23': 'H23 PC RAL',
    'SHARA': 'Brown PC Sahara',
    'BRO': 'Brown PC Sahara',
    'BLACK': 'Black Multi SS Dull',
    'WOOD': None,           # a new finish, owned by Premium
}
STRAY_FINISHES = ('Brown', 'RAL P.C')


def norm_name(text):
    """Two spellings of one name compare equal: case, spaces, dots,
    dashes and underscores are ignored (natural = Natural, h23_pc_ral =
    H23 PC RAL). Odoo-free so the check and the tests run the real one."""
    return re.sub(r'[\s_.\-]+', '', (text or '').lower())


def order_names(names, vendor_id=None):
    """names: [(text, vendor_id, sequence, id)] -> texts, the vendor's own
    first, then the rest in sequence, each spelling once."""
    ordered = sorted(
        names, key=lambda n: (0 if vendor_id and n[1] == vendor_id else 1,
                              n[2], n[3]))
    seen, out = set(), []
    for text, _vendor, _seq, _id in ordered:
        key = norm_name(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


class AwFinishName(models.Model):
    _name = 'aw.finish.name'
    _description = 'Finish Name'
    _order = 'sequence, id'

    finish_id = fields.Many2one(
        'product.attribute.value', required=True, ondelete='cascade',
        index=True)
    name = fields.Char(required=True)
    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', index=True,
        help="Whose name this is. Empty for the finish's own name.")
    sequence = fields.Integer(default=10)

    @api.constrains('name', 'finish_id')
    def _check_unique_name(self):
        for record in self:
            key = norm_name(record.name)
            clash = record.finish_id.aw_name_ids - record
            if any(norm_name(other.name) == key for other in clash):
                raise ValidationError(_(
                    "'%(name)s' is already a name of %(finish)s.",
                    name=record.name, finish=record.finish_id.name))


class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    # Search by ANY of a finish's names.
    _rec_names_search = ['name', 'aw_name_ids.name']

    aw_name_ids = fields.One2many(
        'aw.finish.name', 'finish_id', string='Names')
    aw_customer_name = fields.Char(
        string='Customer name',
        help="Optional. What quotes and shop drawings call this finish; "
             "empty means its own name.")
    aw_owner_vendor_id = fields.Many2one(
        'res.partner', string='Created for vendor',
        help="Set on a finish made from a vendor's own column header "
             "(WOOD). Applying that vendor's list may add the finish to a "
             "profile that does not carry it yet.")

    @api.model_create_multi
    def create(self, vals_list):
        values = super().create(vals_list)
        finish = self.env.ref('aw_fenestration_core.aw_attribute_finish',
                              raise_if_not_found=False)
        for value in values.filtered(
                lambda v: finish and v.attribute_id == finish):
            value._aw_add_name(value.name, self.env['res.partner'])
        return values

    def aw_label(self, vendor=None):
        """The finish's names joined with ' / ', the vendor's first."""
        self.ensure_one()
        names = [(n.name, n.vendor_id.id, n.sequence, n.id)
                 for n in self.aw_name_ids]
        texts = order_names(names, vendor.id if vendor else None)
        if norm_name(self.name) not in {norm_name(t) for t in texts}:
            texts.insert(0, self.name)
        return ' / '.join(texts)

    def aw_doc_name(self):
        """What a customer document calls the finish."""
        self.ensure_one()
        return self.aw_customer_name or self.name

    def _aw_add_name(self, text, vendor):
        """Add `text` as a name of this finish for `vendor`. A spelling the
        finish already has is not added twice; it only gains the vendor if
        it had none."""
        self.ensure_one()
        text = (text or '').strip()
        if not text:
            return self.env['aw.finish.name']
        key = norm_name(text)
        for existing in self.aw_name_ids:
            if norm_name(existing.name) == key:
                if vendor and not existing.vendor_id:
                    existing.vendor_id = vendor
                return existing
        last = max(self.aw_name_ids.mapped('sequence') or [0])
        return self.env['aw.finish.name'].create({
            'finish_id': self.id, 'name': text, 'vendor_id': vendor.id,
            'sequence': last + 10 if self.aw_name_ids else 0})

    # ------------------------------------------------------------------
    # one-time migration
    # ------------------------------------------------------------------
    @api.model
    def _finish_counts(self):
        cr = self.env.cr
        cr.execute("SELECT count(*) FROM aw_profile_rate")
        rates = cr.fetchone()[0]
        cr.execute("SELECT count(*) FROM product_product")
        variants = cr.fetchone()[0]
        cr.execute("SELECT count(*) FROM aw_design")
        designs = cr.fetchone()[0]
        return {'rates': rates, 'variants': variants, 'designs': designs}

    def _stray_attachments(self):
        """{table.column: rows} for everything that still points at this
        finish value, apart from its own names."""
        self.ensure_one()
        # The mapping writes just before this are still in the ORM cache;
        # the count below is raw SQL and must see them.
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("""
            SELECT c.conrelid::regclass::text, a.attname
              FROM pg_constraint c
              JOIN pg_attribute a ON a.attrelid = c.conrelid
                                 AND a.attnum = ANY(c.conkey)
             WHERE c.contype = 'f'
               AND c.confrelid = 'product_attribute_value'::regclass
               AND c.conrelid::regclass::text <> 'aw_finish_name'""")
        found = {}
        for table, column in cr.fetchall():
            cr.execute(
                'SELECT count(*) FROM "%s" WHERE "%s" = %%s' % (table, column),
                (self.id,))
            count = cr.fetchone()[0]
            if count:
                found['%s.%s' % (table, column)] = count
        return found

    @api.model
    def _migrate_finish_names(self):
        """Names for every mapped layout column, Premium's mapping, the
        Wood finish, and the two unused strays removed. Once. Never raises:
        a failure is logged and the next upgrade tries again."""
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(MIGRATED_PARAM):
            return False
        try:
            with self.env.cr.savepoint():
                report = self._do_migrate_finish_names()
        except Exception:
            _logger.exception("aw_fenestration_core: finish names failed")
            return False
        param.set_param(MIGRATED_PARAM, json.dumps(report))
        _logger.info("aw_fenestration_core: finish names: %s", report)
        return report

    @api.model
    def _do_migrate_finish_names(self):
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        Partner = self.env['res.partner'].with_context(active_test=False)
        report = {'before': self._finish_counts(), 'kept': {}, 'deleted': [],
                  'mapped': [], 'created': []}

        finishes = self.search([('attribute_id', '=', finish_attr.id)])
        for finish in finishes:
            finish._aw_add_name(finish.name, Partner)

        # Premium: the confirmed header -> finish table.
        layouts = self.env['aw.vendor.layout'].search([])
        premium = layouts.filtered(
            lambda l: 'premium' in (l.vendor_id.name or '').lower())
        for layout in premium:
            by_name = {norm_name(f.name): f for f in finishes}
            for column in layout.column_ids.filtered(
                    lambda c: c.kind == 'finish'):
                key = next((h for h in PREMIUM_HEADERS
                            if norm_name(h) == norm_name(column.header)),
                           None)
                if key is None:
                    continue
                target = PREMIUM_HEADERS[key]
                if target is None:
                    finish = by_name.get(norm_name(column.header.title()))
                    if not finish:
                        finish = self.create({
                            'attribute_id': finish_attr.id,
                            'name': column.header.title(),
                            'aw_owner_vendor_id': layout.vendor_id.id})
                        by_name[norm_name(finish.name)] = finish
                        report['created'].append(finish.name)
                else:
                    finish = by_name.get(norm_name(target))
                if not finish:
                    continue
                if column.finish_id != finish:
                    column.finish_id = finish
                report['mapped'].append(
                    '%s -> %s' % (column.header, finish.name))

        # Every mapped column adds its header as a name.
        for column in self.env['aw.vendor.layout.column'].search(
                [('kind', '=', 'finish'), ('finish_id', '!=', False)]):
            column.finish_id._aw_add_name(
                column.header, column.layout_id.vendor_id)

        # The unused strays, only if they still hold nothing.
        for name in STRAY_FINISHES:
            stray = self.search([('attribute_id', '=', finish_attr.id),
                                 ('name', '=', name)], limit=1)
            if not stray:
                continue
            rates = self.env['aw.profile.rate'].with_context(
                active_test=False).search_count([('finish_id', '=', stray.id)])
            attached = stray._stray_attachments()
            if rates:
                attached['aw_profile_rate.finish_id'] = rates
            attached.pop('aw_finish_name.finish_id', None)
            if attached:
                report['kept'][name] = attached
                for vendor in premium.vendor_id or Partner.browse():
                    vendor.message_post(body=_(
                        "Finish '%(name)s' was NOT deleted: it is still "
                        "used (%(where)s).",
                        name=name, where=', '.join(
                            '%s: %s' % kv for kv in attached.items())))
                continue
            stray.unlink()
            report['deleted'].append(name)

        report['after'] = self._finish_counts()
        report['names'] = {
            f.name: f.aw_label() for f in self.search(
                [('attribute_id', '=', finish_attr.id)])}
        return report
