# -*- coding: utf-8 -*-
"""Create missing: the products and attribute values a rate list needs.

A preview first; nothing is written until it is confirmed. Then the rows
are re-matched and Apply runs again so the rates land.

What it will and will not do:
  * an unmatched row gets a product made for it (name = the vendor's code,
    category under Profiles by the row's series, UoM ft), with the
    thicknesses and the mapped finishes the list prices as attribute
    values, and the vendor alias is saved;
  * a matched product that lacks a thickness or a mapped finish gets that
    VALUE added to the attribute line it already has -- through the
    attribute-line guard, so never a second line. A product with no line
    for that attribute at all is not changed (adding a whole new attribute
    to a product that has variants would reshape them) and is listed;
  * a rate column with no finish is skipped and listed.
No variants are created here: they stay on demand.
"""
import html
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .rate_paste import normalise_code

_logger = logging.getLogger(__name__)


def _squash(text):
    return ''.join(ch for ch in (text or '').lower() if ch.isalnum())


class AwVendorRateList(models.Model):
    _inherit = 'aw.vendor.rate.list'

    def _profile_category_for(self, series, create=False):
        """The category under Profiles for a vendor series: an existing
        child with the same name (ignoring case and punctuation), else a
        new one when `create`, else the name it would get."""
        root = self.env.ref('aw_fenestration_core.product_category_profiles')
        if not series:
            return root, False
        wanted = _squash(series)
        for child in root.child_id:
            if _squash(child.name) == wanted:
                return child, False
        if create:
            return self.env['product.category'].sudo().create({
                'name': series, 'parent_id': root.id}), True
        return root.browse(), True

    def _missing_plan(self):
        """What Create missing would do, as data."""
        self.ensure_one()
        layout = self._require_layout()
        columns = layout._finish_columns()
        mapped = [(i, c) for i, c in enumerate(columns, start=1)
                  if c.finish_id]
        plan = {
            'create': [], 'extend': [], 'blocked': [],
            'skipped_columns': [
                c.header or str(i) for i, c in enumerate(columns, start=1)
                if not c.finish_id],
        }
        thick_attr = self.env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        Line = self.env['aw.profile.section.line']

        def priced_finishes(lines):
            return finish_attr.value_ids.browse().union(*[
                c.finish_id for i, c in mapped
                if any(line['rate_%s' % i] for line in lines)])

        # ---- unmatched rows, one product per vendor code
        groups = {}
        for line in self.line_ids.filtered(lambda l: not l.product_tmpl_id):
            groups.setdefault(line.code_norm, self.line_ids.browse())
            groups[line.code_norm] |= line
        profiles = self.env['product.template'].search([(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_profiles').id)])
        for norm, lines in groups.items():
            first = lines[0]
            clash = profiles.filtered(
                lambda t: norm in (normalise_code(t.name),
                                   normalise_code(t.default_code)))
            if len(clash) > 1:
                plan['blocked'].append(_(
                    "%s matches several profiles; pick it by hand.",
                    first.code))
                continue
            unresolved = lines.filtered(
                lambda l: l.thickness_text and not l.thickness_id)
            if unresolved:
                plan['blocked'].append(_(
                    "%(code)s: thickness %(thick)s has no alias.",
                    code=first.code,
                    thick=', '.join(sorted({l.thickness_text
                                            for l in unresolved}))))
                continue
            thicknesses = lines.thickness_id
            finishes = priced_finishes(lines)
            category, is_new = self._profile_category_for(first.series)
            plan['create'].append({
                'code': first.code, 'norm': norm, 'series': first.series or '',
                'category': (category.name if category else first.series),
                'category_is_new': is_new,
                'thicknesses': thicknesses.mapped('name'),
                'finishes': finishes.mapped('name'),
                'line_ids': lines.ids,
                'thickness_ids': thicknesses.ids,
                'finish_ids': finishes.ids,
            })

        # ---- matched rows whose product lacks a value
        wanted = {}
        for line in self.line_ids.filtered(
                lambda l: l.product_tmpl_id and not l.problem):
            entry = wanted.setdefault(
                line.product_tmpl_id, {'thick': set(), 'finish': set()})
            if line.thickness_id:
                entry['thick'].add(line.thickness_id.id)
            for i, c in mapped:
                if line['rate_%s' % i]:
                    entry['finish'].add(c.finish_id.id)
        for template, entry in wanted.items():
            add = {}
            for key, attr in (('thick', thick_attr), ('finish', finish_attr)):
                have = Line._template_values(template, attr)
                missing = self.env['product.attribute.value'].browse(
                    sorted(entry[key] - set(have.ids)))
                if not missing:
                    continue
                if not template.attribute_line_ids.filtered(
                        lambda l, a=attr: l.attribute_id == a):
                    plan['blocked'].append(_(
                        "%(profile)s has no %(attr)s attribute, so %(values)s "
                        "cannot be added.",
                        profile=template.display_name, attr=attr.name,
                        values=', '.join(missing.mapped('name'))))
                    continue
                add[key] = missing
            if add:
                plan['extend'].append({
                    'template_id': template.id, 'name': template.display_name,
                    'thickness_ids': add['thick'].ids if 'thick' in add else [],
                    'finish_ids': add['finish'].ids if 'finish' in add else [],
                    'thicknesses': add['thick'].mapped('name')
                    if 'thick' in add else [],
                    'finishes': add['finish'].mapped('name')
                    if 'finish' in add else [],
                })
        return plan

    def _plan_html(self, plan):
        esc = html.escape
        out = []
        out.append('<h5>%s (%s)</h5>' % (
            esc(_("Products to create")), len(plan['create'])))
        out.append('<ul>%s</ul>' % ''.join(
            '<li><b>%s</b> &mdash; %s%s &middot; Thickness: %s &middot; '
            'Finish: %s</li>' % (
                esc(item['code']), esc(item['category'] or ''),
                esc(_(' (new category)')) if item['category_is_new'] else '',
                esc(', '.join(item['thicknesses']) or '-'),
                esc(', '.join(item['finishes']) or '-'))
            for item in plan['create']) or '<li>-</li>')
        out.append('<h5>%s (%s)</h5>' % (
            esc(_("Products to extend")), len(plan['extend'])))
        out.append('<ul>%s</ul>' % ''.join(
            '<li><b>%s</b>: %s</li>' % (esc(item['name']), esc(', '.join(
                item['thicknesses'] + item['finishes'])))
            for item in plan['extend']) or '<li>-</li>')
        if plan['skipped_columns']:
            out.append('<p>%s %s</p>' % (
                esc(_("Columns with no finish are skipped:")),
                esc(', '.join(plan['skipped_columns']))))
        if plan['blocked']:
            out.append('<h5>%s</h5><ul>%s</ul>' % (
                esc(_("Cannot be done")),
                ''.join('<li>%s</li>' % esc(b) for b in plan['blocked'])))
        return ''.join(out)

    def action_create_missing(self):
        """Open the preview. Nothing is written yet."""
        self.ensure_one()
        self._require_layout()
        wizard = self.env['aw.vendor.rate.list.create.wizard'].create(
            {'list_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create missing'),
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def _create_missing(self):
        """Do what the preview showed, then re-match and apply again."""
        self.ensure_one()
        plan = self._missing_plan()
        foot = self.env.ref('uom.product_uom_foot')
        thick_attr = self.env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        Template = self.env['product.template'].sudo()
        Alias = self.env['aw.vendor.alias']
        created = extended = 0
        for item in plan['create']:
            category, _new = self._profile_category_for(
                item['series'], create=True)
            attribute_lines = []
            if item['thickness_ids']:
                attribute_lines.append((0, 0, {
                    'attribute_id': thick_attr.id,
                    'value_ids': [(6, 0, item['thickness_ids'])]}))
            if item['finish_ids']:
                attribute_lines.append((0, 0, {
                    'attribute_id': finish_attr.id,
                    'value_ids': [(6, 0, item['finish_ids'])]}))
            template = Template.create({
                'name': item['code'], 'type': 'consu', 'is_storable': True,
                'uom_id': foot.id, 'categ_id': category.id,
                'sale_ok': False, 'purchase_ok': True,
                'attribute_line_ids': attribute_lines})
            if not Alias.search_count([
                    ('vendor_id', '=', self.vendor_id.id),
                    ('code_norm', '=', item['norm']),
                    ('thickness_text', 'in', (False, ''))]):
                Alias.create({
                    'vendor_id': self.vendor_id.id,
                    'code_norm': item['norm'],
                    'product_tmpl_id': template.id})
            created += 1
        for item in plan['extend']:
            template = Template.browse(item['template_id'])
            commands = []
            if item['thickness_ids']:
                commands.append((0, 0, {
                    'attribute_id': thick_attr.id,
                    'value_ids': [(6, 0, item['thickness_ids'])]}))
            if item['finish_ids']:
                commands.append((0, 0, {
                    'attribute_id': finish_attr.id,
                    'value_ids': [(6, 0, item['finish_ids'])]}))
            # The attribute-line guard merges these into the existing
            # lines rather than adding a second one.
            template.write({'attribute_line_ids': commands})
            extended += 1
        self.line_ids.filtered(lambda l: not l.product_tmpl_id)._auto_match()
        summary = self._apply()
        summary.update({'created': created, 'extended': extended,
                        'blocked': plan['blocked']})
        _logger.info("aw_fenestration_core: create missing: %s", summary)
        return summary


class AwVendorRateListCreateWizard(models.TransientModel):
    _name = 'aw.vendor.rate.list.create.wizard'
    _description = 'Create missing products for a rate list'

    list_id = fields.Many2one(
        'aw.vendor.rate.list', required=True, readonly=True)
    preview = fields.Html(compute='_compute_preview', sanitize=False)

    @api.depends('list_id')
    def _compute_preview(self):
        for wizard in self:
            plan = wizard.list_id._missing_plan()
            wizard.preview = wizard.list_id._plan_html(plan)

    def action_confirm(self):
        self.ensure_one()
        summary = self.list_id._create_missing()
        message = _(
            "Created %(created)s product(s), extended %(extended)s. "
            "Rates: %(applied)s applied, %(skipped)s column(s) skipped, "
            "%(failed)s failed.",
            created=summary['created'], extended=summary['extended'],
            applied=summary['applied'], skipped=summary['skipped'],
            failed=summary['failed'])
        self.list_id.message_post(body=message)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if not summary['failed'] else 'warning',
                'message': message, 'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'}},
        }
