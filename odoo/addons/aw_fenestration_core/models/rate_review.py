# -*- coding: utf-8 -*-
"""Review, Confirm and Undo for a rate list.

Nothing is written before Confirm. Review compares every row of the list with
the rate in force today for the same key (profile, thickness, finish and vendor;
or glass type, thickness and vendor) and says, in plain words, what Confirm
would do:

  Unchanged   the same price is already in force (only counted)
  Changed     a different price; old, new and percent are shown, and a change
              over 15% is red and needs one tick
  New         no rate for that key yet
  Problems    block Confirm: two prices for one key in the same list, or a
              newer rate for that key is already in force, so this list would
              be overruled
  Not written the product, thickness, finish or glass type is missing; the row
              is listed and left out, and does not block (rows waiting for a
              product are normal)

An empty price is "no price": counted and ignored, never a 0.
"""
import base64
import csv
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError

BIG_CHANGE_PCT = 15.0


class AwVendorRateReview(models.Model):
    _name = 'aw.vendor.rate.review'
    _description = 'Rate List Review Row'
    _order = 'sort, id'

    list_id = fields.Many2one(
        'aw.vendor.rate.list', required=True, ondelete='cascade', index=True)
    line_id = fields.Many2one('aw.vendor.rate.list.line', ondelete='cascade')
    sort = fields.Integer()
    status = fields.Selection([
        ('changed', 'Changed'), ('new', 'New'), ('problem', 'Problem'),
        ('notwritten', 'Not written')], required=True)
    code = fields.Char(string='Profile')
    thickness = fields.Char()
    finish = fields.Char()
    old_price = fields.Float(digits='Product Price')
    new_price = fields.Float(digits='Product Price')
    pct = fields.Float(string='Change %', digits=(16, 1))
    big = fields.Boolean(string='Over 15%')
    message = fields.Char()


class AwVendorRateList(models.Model):
    _inherit = 'aw.vendor.rate.list'

    review_ids = fields.One2many('aw.vendor.rate.review', 'list_id')
    review_unchanged = fields.Integer(readonly=True, copy=False)
    review_changed = fields.Integer(readonly=True, copy=False)
    review_new = fields.Integer(readonly=True, copy=False)
    review_problem = fields.Integer(readonly=True, copy=False)
    review_notwritten = fields.Integer(readonly=True, copy=False)
    review_nopriced = fields.Integer(readonly=True, copy=False)
    review_big = fields.Integer(readonly=True, copy=False)
    ack_changes = fields.Boolean(
        string="I checked these price changes", copy=False)
    review_summary = fields.Char(compute='_compute_review_summary')
    review_big_text = fields.Char(compute='_compute_review_summary')

    @api.depends('review_unchanged', 'review_changed', 'review_new',
                 'review_problem', 'review_notwritten', 'review_nopriced',
                 'review_big')
    def _compute_review_summary(self):
        for rec in self:
            rec.review_summary = _(
                "Unchanged %(unchanged)s  |  Changed %(changed)s  |  "
                "New %(new)s  |  Problems %(problem)s  |  Not written "
                "%(notwritten)s",
                unchanged=rec.review_unchanged, changed=rec.review_changed,
                new=rec.review_new, problem=rec.review_problem,
                notwritten=rec.review_notwritten)
            parts = []
            if rec.review_big:
                parts.append(_(
                    "%s price change(s) are over %g%% and are shown in red.",
                    rec.review_big, BIG_CHANGE_PCT))
            if rec.review_nopriced:
                parts.append(_(
                    "%s empty price cell(s) are ignored.", rec.review_nopriced))
            rec.review_big_text = ' '.join(parts)

    # -------------------------------------------------------------- building
    def _review_data(self):
        """{'rows': [...], 'counts': {...}} without writing anything."""
        self.ensure_one()
        if self.kind == 'glass':
            return self._review_glass()
        return self._review_profile()

    @staticmethod
    def _plain_need(line):
        """A row that cannot be written yet, in plain words."""
        need = line.need
        code = line.code
        if line.ambiguous_code:
            return _("The code %s could mean two profiles, so this row is "
                     "not written.", code)
        if need == 'product' or (line.problem and not line.product_tmpl_id):
            return _("There is no profile with the code %s yet, so this row "
                     "is not written. Add the product first.", code)
        if need == 'unknown_thickness' or (
                line.thickness_text and not line.thickness_id
                and line.list_id.kind != 'glass'):
            return _("%(code)s: the thickness '%(thickness)s' is not one we "
                     "know, so this row is not written.",
                     code=code, thickness=line.thickness_text or '')
        if need == 'glass_type':
            return _("There is no glass type %s yet, so this row is not "
                     "written. Add the glass type first.", code)
        text = (line.need_text or '').replace(', then Re-match', '')
        return _("Not written: %s", text) if text else _(
            "%s cannot be written yet.", code)

    def _row(self, line, status, **values):
        return dict({
            'line_id': line.id, 'sort': line.sequence, 'status': status,
            'code': line.code, 'thickness': line.thickness_text or '',
            'can_match': (status == 'notwritten' and not line.product_tmpl_id
                          and line.list_id.kind == 'profile'),
        }, **values)

    def _classify(self, current, newer, price):
        """(status, old price, percent) for one key."""
        if newer:
            return 'problem', current.price if current else 0.0, 0.0
        if not current:
            return 'new', 0.0, 0.0
        if abs(current.price - price) < 0.005:
            return 'unchanged', current.price, 0.0
        return 'changed', current.price, (
            (price - current.price) / current.price * 100.0
            if current.price else 0.0)

    def _review_profile(self):
        self.ensure_one()
        layout = self._require_layout()
        finish_columns = layout._finish_columns()
        Rate = self.env['aw.profile.rate'].with_context(active_test=False)
        today = fields.Date.context_today(self)
        Section = self.env['aw.profile.section.line']
        thickness_attr = self.env.ref('aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref('aw_fenestration_core.aw_attribute_finish')
        rows, counts = [], dict.fromkeys(
            ('unchanged', 'changed', 'new', 'problem', 'notwritten',
             'nopriced', 'big'), 0)
        for line in self.line_ids.sorted('sequence'):
            line._refresh_need()
            if line.problem or line.need:
                counts['notwritten'] += 1
                rows.append(self._row(
                    line, 'notwritten', message=self._plain_need(line)))
                continue
            template = line.product_tmpl_id
            label = template.default_code or template.name or line.code
            thickness = line.thickness_id.name or line.thickness_text or ''
            offered_thickness = Section._template_values(template, thickness_attr)
            offered_finish = Section._template_values(template, finish_attr)
            by_finish = {}
            for index, column in enumerate(finish_columns, start=1):
                price = line['rate_%s' % index]
                if not price:
                    counts['nopriced'] += 1
                    continue
                if not column.finish_id:
                    continue
                by_finish.setdefault(column.finish_id, []).append(
                    (column, price))
            for finish, cells in by_finish.items():
                base = {'code': label, 'thickness': thickness,
                        'finish': finish.name}
                if len({price for _c, price in cells}) > 1:
                    counts['problem'] += 1
                    rows.append(self._row(line, 'problem', **dict(base, message=_(
                        "%(code)s %(thickness)s: the columns %(columns)s all "
                        "mean %(finish)s but show different prices (%(prices)s). "
                        "Nothing is written for this finish; keep one price.",
                        code=label, thickness=thickness, finish=finish.name,
                        columns=' and '.join(
                            c.header or finish.name for c, _p in cells),
                        prices=' and '.join('%g' % p for _c, p in cells)))))
                    continue
                price = cells[0][1]
                if (line.thickness_id
                        and line.thickness_id not in offered_thickness) or (
                        finish not in offered_finish
                        and finish.aw_owner_vendor_id != self.vendor_id):
                    counts['notwritten'] += 1
                    rows.append(self._row(line, 'notwritten', **dict(base, message=_(
                        "%(code)s is not sold in %(thickness)s / %(finish)s, "
                        "so this price is not written. Add it to the product "
                        "first.", code=label, thickness=thickness or _('this thickness'),
                        finish=finish.name))))
                    continue
                key = [('product_tmpl_id', '=', template.id),
                       ('thickness_id', '=', line.thickness_id.id or False),
                       ('finish_id', '=', finish.id),
                       ('vendor_id', '=', self.vendor_id.id)]
                current = Rate.search(
                    key + [('date_from', '<=', self.date),
                           ('rate_list_id', '!=', self.id)],
                    order='date_from desc, id desc', limit=1)
                same_day = Rate.search(
                    key + [('date_from', '=', self.date)], limit=1)
                current = same_day or current
                newer = Rate.search(
                    key + [('date_from', '>', self.date),
                           ('date_from', '<=', today)],
                    order='date_from desc', limit=1)
                self._review_cell(
                    rows, counts, line, base, current, newer, price)
        return {'rows': rows, 'counts': counts}

    def _review_cell(self, rows, counts, line, base, current, newer, price):
        status, old, pct = self._classify(current, newer, price)
        if status == 'unchanged':
            counts['unchanged'] += 1
            return
        counts[status] += 1
        values = dict(base, old_price=old, new_price=price, pct=pct)
        if status == 'problem':
            values['message'] = _(
                "%(what)s: a newer rate of %(rate)s from %(date)s is already "
                "in force. This list starts on %(start)s, so it would be "
                "overruled. Remove this row or choose a later date.",
                what=' '.join(x for x in (
                    base.get('code'), base.get('thickness'),
                    base.get('finish')) if x),
                rate='%g' % newer.price, date=newer.date_from,
                start=self.date)
        elif status == 'changed':
            values['big'] = abs(pct) > BIG_CHANGE_PCT
            if values['big']:
                counts['big'] += 1
            values['message'] = _(
                "%(old)s to %(new)s (%(pct)+.1f%%)",
                old='%g' % old, new='%g' % price, pct=pct)
        else:
            values['message'] = _("New rate %s", '%g' % price)
        rows.append(self._row(line, status, **values))

    def _review_glass(self):
        self.ensure_one()
        from .glass_paste import parse_thickness
        Rate = self.env['aw.glass.rate'].with_context(active_test=False)
        today = fields.Date.context_today(self)
        rows, counts = [], dict.fromkeys(
            ('unchanged', 'changed', 'new', 'problem', 'notwritten',
             'nopriced', 'big'), 0)
        priced = {}
        for line in self.line_ids:
            line._refresh_need()
            if not line.need and line.rate_1:
                priced.setdefault(
                    (line.glass_type_id.id, parse_thickness(line.thickness_text)[0]),
                    []).append(line)
        conflicts = {}
        for key, lines in priced.items():
            if len({round(l.rate_1, 4) for l in lines}) > 1:
                for l in lines:
                    conflicts[l.id] = sorted({x.rate_1 for x in lines})
        for line in self.line_ids.sorted('sequence'):
            if line.need:
                counts['notwritten'] += 1
                rows.append(self._row(line, 'notwritten',
                                      message=self._plain_need(line)))
                continue
            if not line.rate_1:
                counts['nopriced'] += 1
                continue
            base = {'code': line.glass_type_id.name or line.code,
                    'thickness': line.thickness_text or ''}
            if line.id in conflicts:
                counts['problem'] += 1
                rows.append(self._row(line, 'problem', **dict(base, message=_(
                    "%(type)s %(thickness)s has %(prices)s in this list. "
                    "Nothing is written for it; keep one price.",
                    type=base['code'], thickness=base['thickness'],
                    prices=' and '.join('%g' % p for p in conflicts[line.id])))))
                continue
            thickness = parse_thickness(line.thickness_text)[0]
            key = [('glass_type_id', '=', line.glass_type_id.id),
                   ('thickness_mm', '=', thickness),
                   ('vendor_id', '=', self.vendor_id.id)]
            current = Rate.search(
                key + [('date_from', '<=', self.date),
                       ('rate_list_id', '!=', self.id)],
                order='date_from desc, id desc', limit=1)
            current = Rate.search(
                key + [('date_from', '=', self.date)], limit=1) or current
            newer = Rate.search(
                key + [('date_from', '>', self.date),
                       ('date_from', '<=', today)],
                order='date_from desc', limit=1)
            self._review_cell(
                rows, counts, line, base, current, newer, line.rate_1)
        return {'rows': rows, 'counts': counts}

    # ------------------------------------------------------------- the steps
    def _store_review(self, data):
        self.ensure_one()
        counts = data['counts']
        self.review_ids.unlink()
        self.env['aw.vendor.rate.review'].create([
            dict(row, list_id=self.id) for row in data['rows']])
        self.write({
            'review_unchanged': counts['unchanged'],
            'review_changed': counts['changed'],
            'review_new': counts['new'],
            'review_problem': counts['problem'],
            'review_notwritten': counts['notwritten'],
            'review_nopriced': counts['nopriced'],
            'review_big': counts['big'],
            'ack_changes': False,
        })

    def _reset_review(self):
        """The rows changed under a review: it is no longer true."""
        for rec in self.filtered(lambda r: r.step == 'review'):
            rec.review_ids.unlink()
            rec.write({'step': 'data', 'ack_changes': False})

    def action_open_review(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("This list is already applied."))
        if not self.line_ids:
            raise UserError(_(
                "There are no rows to review yet. Add the prices first."))
        self._store_review(self._review_data())
        self.step = 'review'
        return True

    def action_back_to_data(self):
        self.ensure_one()
        if self.state == 'draft':
            self._reset_review()
            if self.step != 'choose':
                self.step = 'data'
        return True

    def action_confirm_rates(self):
        """Write the rates. Checked again here, on the rows as they are now,
        because the review on screen may be older than the rows."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("This list is already applied."))
        if self.step != 'review':
            raise UserError(_("Press Review first and look at the changes."))
        fresh = self._review_data()
        counts = fresh['counts']
        if counts['problem']:
            self._store_review(fresh)
            raise UserError(_(
                "%s problem(s) must be fixed before these rates can be "
                "confirmed. They are listed in red.", counts['problem']))
        if counts['big'] and not self.ack_changes:
            raise UserError(_(
                "%s price change(s) are over %g%%. Look at them, then tick "
                "\"I checked these price changes\".",
                counts['big'], BIG_CHANGE_PCT))
        # a price that is already in force is not written again
        summary = self.with_context(aw_skip_unchanged=True)._apply()
        self._keep_typed_copy()
        self.step = 'confirm'
        self.message_post(body=_(
            "Confirmed: %(written)s rate(s) written (%(changed)s changed, "
            "%(new)s new, %(unchanged)s unchanged, %(notwritten)s row(s) not "
            "written).",
            written=summary['applied'], changed=counts['changed'],
            new=counts['new'], unchanged=counts['unchanged'],
            notwritten=counts['notwritten']))
        return True

    def _keep_typed_copy(self):
        """The original stays with the list. A pasted sheet is attached when
        it is read; rows typed in the table have no file, so they are kept as
        one, as they stood when confirmed."""
        self.ensure_one()
        if self.env['ir.attachment'].search_count([
                ('res_model', '=', self._name), ('res_id', '=', self.id)]):
            return False
        out = io.StringIO()
        writer = csv.writer(out)
        if self.kind == 'glass':
            writer.writerow(['glass type', 'thickness', 'price per sqft'])
            for line in self.line_ids.sorted('sequence'):
                writer.writerow([line.code, line.thickness_text, line.rate_1])
        else:
            columns = self.layout_id._finish_columns()
            writer.writerow(['code', 'thickness', 'series'] + [
                c.header or c.finish_id.name for c in columns])
            for line in self.line_ids.sorted('sequence'):
                writer.writerow([line.code, line.thickness_text, line.series] + [
                    line['rate_%s' % i] or '' for i in range(1, len(columns) + 1)])
        return self.env['ir.attachment'].create({
            'name': 'rates-%s-%s.csv' % (self.vendor_id.name, self.date),
            'res_model': self._name, 'res_id': self.id,
            'raw': out.getvalue().encode('utf-8'), 'mimetype': 'text/csv'})


class AwVendorRateListLineReview(models.Model):
    _inherit = 'aw.vendor.rate.list.line'

    # What a person types or matches. A change to any of it makes a review on
    # screen untrue; the bookkeeping Apply and Re-match write does not.
    REVIEW_INPUTS = {
        'code', 'thickness_text', 'series', 'product_tmpl_id', 'thickness_id',
        'glass_type_id'} | {'rate_%d' % i for i in range(1, 11)}

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.list_id._reset_review()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if self.REVIEW_INPUTS & set(vals) and not self.env.context.get(
                'aw_need') and not self.env.context.get('aw_auto_match'):
            self.list_id._reset_review()
        return result

    def unlink(self):
        lists = self.list_id
        result = super().unlink()
        lists._reset_review()
        return result
