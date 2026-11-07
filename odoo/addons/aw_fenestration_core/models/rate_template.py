# -*- coding: utf-8 -*-
"""Download the Excel template for a rate list (3a of the template flow).

Two kinds of file, both made by `rate_xlsx.build_template`:

  Blank              a header row only, fully unlocked.
  With current rates the codes, thicknesses and prices in force today for the
                     vendor, for one series or for everything, with locked
                     identity cells, open price cells and a "New items" block.

The series is asked first (a wizard), because the whole catalogue can be a
few thousand rows. Nothing is written to the list or to any rate by
downloading; reading the file back is Upload (the next change).
"""
import base64
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import rate_xlsx

LARGE_FILE_ROWS = 400


def _safe(text):
    return re.sub(r'[^A-Za-z0-9]+', '_', text or '').strip('_') or 'x'


def _mm_text(value):
    """6.0 -> 6, 4.5 -> 4.5: a glass thickness as a number cell."""
    return int(value) if float(value).is_integer() else float(value)


class AwVendorRateListTemplate(models.Model):
    _inherit = 'aw.vendor.rate.list'

    def _template_wizard(self, mode):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("An applied list is read only."))
        if self.kind == 'profile':
            self._require_layout()
        wizard = self.env['aw.vendor.rate.template.wizard'].create({
            'list_id': self.id, 'mode': mode})
        if mode == 'blank' or self.kind == 'glass':
            wizard.action_make_file()
        return wizard._reopen()

    def action_template_blank(self):
        return self._template_wizard('blank')

    def action_template_current(self):
        return self._template_wizard('current')


class AwVendorRateTemplateWizard(models.TransientModel):
    _name = 'aw.vendor.rate.template.wizard'
    _description = 'Download the rate template'

    list_id = fields.Many2one('aw.vendor.rate.list', required=True,
                              ondelete='cascade')
    mode = fields.Selection([
        ('blank', 'Blank'), ('current', 'With current rates'),
    ], required=True, default='blank')
    kind = fields.Selection(related='list_id.kind')
    series = fields.Char(help="The vendor's series name, as in the rates.")
    everything = fields.Boolean(
        string="Everything", help="Every series of this vendor.")
    series_choices = fields.Char(compute='_compute_choices')
    row_count = fields.Integer(compute='_compute_choices')
    size_warning = fields.Char(compute='_compute_choices')
    file_data = fields.Binary(readonly=True, attachment=False)
    file_name = fields.Char(readonly=True)

    # ------------------------------------------------------------- compute
    def _today(self):
        return fields.Date.context_today(self)

    def _in_force_domain(self, vendor):
        today = self._today()
        return [('vendor_id', '=', vendor.id), ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today)]

    def _profile_rates(self):
        self.ensure_one()
        domain = self._in_force_domain(self.list_id.vendor_id)
        if not self.everything:
            domain.append(('vendor_series', '=ilike', self.series or ''))
        return self.env['aw.profile.rate'].search(domain)

    @api.depends('series', 'everything', 'mode', 'list_id')
    def _compute_choices(self):
        for wiz in self:
            wiz.series_choices = wiz.row_count = wiz.size_warning = False
            if not wiz.list_id or wiz.mode != 'current' \
                    or wiz.list_id.kind != 'profile':
                continue
            domain = wiz._in_force_domain(wiz.list_id.vendor_id)
            every = self.env['aw.profile.rate'].search(domain)
            names = sorted({r.vendor_series for r in every if r.vendor_series})
            wiz.series_choices = ', '.join(names) or _("none")
            chosen = wiz._profile_rates()
            wiz.row_count = len({(r.product_tmpl_id.id, r.thickness_id.id)
                                 for r in chosen})
            if wiz.everything and wiz.row_count > LARGE_FILE_ROWS:
                wiz.size_warning = _(
                    "Everything is %s rows. The file will be big and slow "
                    "to open and check; pick a series if you only price one.",
                    wiz.row_count)

    # ---------------------------------------------------------------- rows
    def _profile_rows(self, layout):
        self.ensure_one()
        finish_columns = layout._finish_columns()
        names = {a.thickness_id.id: a.alias
                 for a in layout.thickness_alias_ids}
        groups = {}
        for rate in self._profile_rates():
            groups.setdefault(
                (rate.product_tmpl_id, rate.thickness_id), []).append(rate)
        rows = []
        for (template, thickness), group in sorted(
                groups.items(), key=lambda kv: (
                    kv[0][0].display_name, kv[0][1].id or 0)):
            prices = []
            for column in finish_columns:
                hit = next((r for r in group if column.finish_id
                            and r.finish_id == column.finish_id), None)
                prices.append(hit.price if hit else None)
            series = next((r.vendor_series for r in group
                           if r.vendor_series), '')
            rows.append({
                'key': 'p:%s:%s' % (template.id, thickness.id),
                'cells': [template.default_code or template.name,
                          names.get(thickness.id, thickness.name or ''),
                          series] + prices})
        return rows

    def _glass_rows(self):
        self.ensure_one()
        rates = self.env['aw.glass.rate'].search(
            self._in_force_domain(self.list_id.vendor_id))
        rows = []
        for rate in sorted(rates, key=lambda r: (
                r.glass_type_id.display_name, r.thickness_mm)):
            rows.append({
                'key': 'g:%s:%s' % (rate.glass_type_id.id, rate.thickness_mm),
                'cells': [rate.glass_type_id.display_name,
                          _mm_text(rate.thickness_mm), rate.price]})
        return rows

    # -------------------------------------------------------------- action
    def action_make_file(self):
        self.ensure_one()
        rate_list = self.list_id
        layout = (rate_list._require_layout()
                  if rate_list.kind == 'profile' else None)
        current = self.mode == 'current'
        if current and rate_list.kind == 'profile' \
                and not (self.everything or (self.series or '').strip()):
            raise UserError(_(
                "Which series? Type one (%s) or tick Everything.",
                self.series_choices or _("none")))
        if current:
            rows = (self._profile_rows(layout) if layout
                    else self._glass_rows())
            if not rows:
                raise UserError(_(
                    "%(vendor)s has no current rates for that. Use the "
                    "blank template instead.",
                    vendor=rate_list.vendor_id.display_name))
        else:
            rows = []
        stamp = fields.Datetime.context_timestamp(
            self, fields.Datetime.now()).strftime('%Y-%m-%d %H:%M')
        content = 'With current rates' if current else 'Blank template'
        info = {
            'vendor': rate_list.vendor_id.display_name,
            'vendor_id': rate_list.vendor_id.id,
            'date': fields.Date.to_string(rate_list.date),
            'list_id': rate_list.id, 'content': content, 'downloaded': stamp,
            'series': ('' if rate_list.kind == 'glass' or not current else (
                'Everything' if self.everything else self.series.strip())),
        }
        try:
            data = rate_xlsx.build_template(
                info, rate_list.kind,
                [c.header for c in layout._finish_columns()] if layout else (),
                rows, prefilled=current)
        except RuntimeError as error:
            raise UserError(str(error))
        self.write({
            'file_data': base64.b64encode(data),
            'file_name': 'rates_%s_%s_%s_%s.xlsx' % (
                _safe(rate_list.vendor_id.display_name), rate_list.kind,
                info['date'], 'current' if current else 'blank')})
        rate_list.message_post(body=_(
            "Template downloaded: %(content)s%(series)s.",
            content=content.lower(),
            series=(', series ' + info['series']) if info['series'] else ''))
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Rate template"),
            'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new',
        }
