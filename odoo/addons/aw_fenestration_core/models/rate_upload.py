# -*- coding: utf-8 -*-
"""Upload a filled-in rate template (3b of the template flow).

The file is read by `rate_xlsx.read_template`; this model decides whether it
belongs to the list, turns what was read into ordinary list lines, and says
what it did. It never writes a rate: the lines go through Review and Confirm
like any others. A file with any problem loads NOTHING and names every row, as
a bad paste does.

A blank price is "leave unchanged": the cell is counted, the line carries 0.0
(which Apply and Review treat as no price) and no existing rate is touched. A
row with no price at all is not loaded.
"""
import base64

from odoo import _, fields, models
from odoo.exceptions import UserError

from . import rate_xlsx

SHOWN_PROBLEMS = 12
XLSX_MIME = ('application/vnd.openxmlformats-officedocument.'
             'spreadsheetml.sheet')


class AwVendorRateListUpload(models.Model):
    _inherit = 'aw.vendor.rate.list'

    upload_summary = fields.Text(
        readonly=True, copy=False,
        help="What the last uploaded file contained and what was done.")

    def action_clear_lines(self):
        """Take every row off a draft list, to start the data again. Rates
        manager only; nothing already written as a rate is touched."""
        self.ensure_one()
        if not self.env.user.has_group(
                'aw_fenestration_core.group_rates_manager'):
            raise UserError(_("Only a Rates manager can clear a list."))
        if self.state != 'draft':
            raise UserError(_("An applied list is read only. Undo it first."))
        count = len(self.line_ids)
        self.line_ids.unlink()
        self._reset_review()
        self.write({'upload_summary': False, 'step': 'data'
                    if self.step != 'choose' else 'choose'})
        self.message_post(body=_(
            "%(who)s cleared all %(count)s line(s) of this list.",
            who=self.env.user.name, count=count))
        return True

    def action_upload_template(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("An applied list is read only."))
        if self.line_ids:
            raise UserError(_(
                "This list already has lines. Clear them first."))
        if self.kind == 'profile':
            self._require_layout()
        wizard = self.env['aw.vendor.rate.upload.wizard'].create({
            'list_id': self.id})
        return {
            'type': 'ir.actions.act_window', 'name': _("Upload the file"),
            'res_model': wizard._name, 'res_id': wizard.id,
            'view_mode': 'form', 'views': [(False, 'form')],
            'target': 'new'}

    def _expected_info(self):
        self.ensure_one()
        return {
            'vendor': self.vendor_id.display_name,
            'vendor_id': str(self.vendor_id.id),
            'kind': 'Glass' if self.kind == 'glass' else 'Profiles',
            'date': fields.Date.to_string(self.date),
            'list_id': str(self.id),
            'version': str(rate_xlsx.TEMPLATE_VERSION)}

    def _key_lookup(self, layout):
        """key -> what the hidden key stands for, for the reader to compare
        with the code and thickness beside it. None when it names nothing."""
        names = ({a.thickness_id.id: a.alias for a in layout.thickness_alias_ids}
                 if layout else {})
        env = self.env

        def lookup(key):
            parts = (key or '').split(':')
            try:
                if parts[0] == 'p' and len(parts) == 3:
                    template = env['product.template'].browse(
                        int(parts[1])).exists()
                    value = env['product.attribute.value'].browse(
                        int(parts[2])).exists()
                    if template and value:
                        return {'code': template.default_code or template.name,
                                'thickness': names.get(value.id,
                                                       value.name or ''),
                                'template': template.id, 'thickness_id': value.id}
                if parts[0] == 'g' and len(parts) == 3:
                    glass = env['aw.glass.type'].browse(int(parts[1])).exists()
                    if glass:
                        return {'code': glass.display_name,
                                'thickness': float(parts[2])}
            except (ValueError, TypeError):
                return None
            return None
        return lookup

    def _load_uploaded(self, data, file_name):
        """Read the file and add its lines. Returns the summary text."""
        self.ensure_one()
        if self.line_ids:
            raise UserError(_(
                "This list already has lines. Clear them first."))
        layout = self._require_layout() if self.kind == 'profile' else None
        finishes = layout._finish_columns() if layout else ()
        lookup = self._key_lookup(layout)
        cache = {}

        def cached(key):
            if key not in cache:
                cache[key] = lookup(key)
            return cache[key]

        result = rate_xlsx.read_template(
            data, self.kind, [c.header for c in finishes],
            self._expected_info(), cached)
        if result['errors']:
            raise UserError(_("Nothing was loaded. %s", result['errors'][0]))
        if result['problems']:
            shown = result['problems'][:SHOWN_PROBLEMS]
            more = len(result['problems']) - len(shown)
            raise UserError(_(
                "Nothing was loaded from this file. Fix these cells in Excel "
                "and upload it again:\n%(problems)s%(more)s",
                problems='\n'.join(shown),
                more=_("\nand %s more.", more) if more else ''))

        start = (self.line_ids[-1:].sequence or 0) if self.line_ids else 0
        vals, no_price = [], 0
        for row in result['rows']:
            if all(price is None for price in row['prices']):
                no_price += 1
                continue
            values = {
                'list_id': self.id,
                'sequence': start + 10 * (len(vals) + 1),
                'code': row['code'],
                'thickness_text': (
                    '%smm' % ('%g' % row['thickness'])
                    if self.kind == 'glass' else row['thickness']),
                'series': row['series'] or False,
            }
            for index, price in enumerate(row['prices'][:10], start=1):
                values['rate_%s' % index] = price or 0.0
            known = cached(row['key']) if row['key'] else None
            if known and self.kind == 'profile':
                values.update(
                    product_tmpl_id=known['template'],
                    thickness_id=known['thickness_id'],
                    match_source='direct')
            vals.append(values)
        if not vals:
            raise UserError(_(
                "Nothing was loaded: the file has no price in it. Type the "
                "prices that change and upload it again."))
        self.env['aw.vendor.rate.list.line'].with_context(
            aw_no_alias=True).create(vals)

        new_items = sum(1 for r in result['rows'] if r['new']
                        and not all(p is None for p in r['prices']))
        lines = [_("%(file)s: %(rows)s row(s) loaded, %(new)s of them typed "
                   "under New items.", file=file_name, rows=len(vals),
                   new=new_items)]
        if result['blank_cells']:
            lines.append(_(
                "%s price cell(s) were empty: left unchanged, nothing is "
                "written for them.", result['blank_cells']))
        if no_price:
            lines.append(_(
                "%s row(s) had no price at all and were not loaded.",
                no_price))
        lines.extend(result['notes'])
        summary = '\n'.join(lines)
        self.env['ir.attachment'].create({
            'name': file_name or 'rates.xlsx', 'res_model': self._name,
            'res_id': self.id, 'raw': data, 'mimetype': XLSX_MIME})
        self.upload_summary = summary
        self.message_post(body=summary.replace('\n', '<br/>'))
        return summary


class AwVendorRateUploadWizard(models.TransientModel):
    _name = 'aw.vendor.rate.upload.wizard'
    _description = 'Upload the filled-in rate template'

    list_id = fields.Many2one('aw.vendor.rate.list', required=True,
                              ondelete='cascade')
    file_data = fields.Binary(string="Excel file", attachment=False)
    file_name = fields.Char()

    def action_read(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Choose the Excel file first."))
        rate_list = self.list_id
        if rate_list.state != 'draft':
            raise UserError(_("An applied list is read only."))
        summary = rate_list._load_uploaded(
            base64.b64decode(self.file_data), self.file_name or 'rates.xlsx')
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("File loaded"), 'message': summary,
                       'type': 'success', 'sticky': True,
                       'next': {'type': 'ir.actions.act_window_close'}}}
