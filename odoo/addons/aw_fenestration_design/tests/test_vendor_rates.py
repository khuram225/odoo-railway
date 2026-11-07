# -*- coding: utf-8 -*-
"""Vendor rate lists: pasting, matching, applying, and costing at one
vendor's rates only."""
from datetime import date

from odoo.addons.aw_fenestration_core.models.rate_paste import (
    canonical_code, normalise_code, parse_paste, split_codes)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

KINDS = ['code', 'thickness', 'series'] + ['finish'] * 7


@tagged('post_install', '-at_install')
class TestRatePaste(TransactionCase):
    """The parser alone."""

    def test_codes_ignore_case_spaces_and_hyphens(self):
        self.assertEqual(normalise_code('D35'), normalise_code('d-35'))
        self.assertEqual(normalise_code(' D 35 '), 'D35')
        # suffix words stay: a different profile
        self.assertNotEqual(
            normalise_code('D-35 M.F'), normalise_code('D-35'))

    def test_codes_have_one_canonical_spelling(self):
        for raw, canonical in (('D38F', 'D-38F'), ('D 38F', 'D-38F'),
                               ('D.40', 'D-40'), ('D-40', 'D-40'),
                               ('D-35 M.F', 'D-35 M.F')):
            self.assertEqual(canonical_code(raw), canonical, raw)
        self.assertEqual(normalise_code('D.40'), normalise_code('D-40'))
        self.assertEqual(normalise_code('D 38F'), normalise_code('D38F'))

    def test_a_typed_row_with_a_blank_series(self):
        rows = parse_paste('B-6  NOR  136 147 137 137 153 147 171', KINDS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], 'B-6')
        self.assertEqual(rows[0]['thickness'], 'NOR')
        self.assertEqual(
            rows[0]['rates'],
            [136.0, 147.0, 137.0, 137.0, 153.0, 147.0, 171.0])

    def test_tab_rows_header_skipped_and_series_carried_down(self):
        text = (
            'SEC.NO.\tThickness\tSeries\tDULL\tBRO\tH.23\tRAL P.C\tBLACK'
            '\tSHARA\tWOOD\n'
            'D-35\tNOR\tDG.SERIES\t100\t110\t\t\t\t\t\n'
            'D-36\tNOR\t\t101\t111\t\t\t\t\t')
        rows = parse_paste(text, KINDS)
        self.assertEqual([r['code'] for r in rows], ['D-35', 'D-36'])
        self.assertEqual(rows[1]['series'], 'DG.SERIES')
        self.assertEqual(rows[0]['rates'][:3], [100.0, 110.0, None])


    def test_excel_rows_with_an_empty_series_and_crlf(self):
        text = (
            'B-6\tNOR\t\t136\t147\t137\t137\t153\t147\t171\r\n'
            'D-10\tNOR\t\t514\t552\t516\t516\t578\t552\t645\r\n'
            'D-10\t1.6MM\t\t647\t694\t649\t649\t727\t694\t811\r\n')
        rows = parse_paste(text, KINDS)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['thickness'] for r in rows],
                         ['NOR', 'NOR', '1.6MM'])
        self.assertEqual(rows[2]['rates'][0], 647.0)
        # nothing shifted into the series column
        self.assertEqual([r['series'] for r in rows], ['', '', ''])

    def test_numbers_with_commas_and_quotes(self):
        rows = parse_paste('A-1\tNOR\t\t"1,136"\t147\t\t\t\t\t', KINDS)
        self.assertEqual(rows[0]['rates'][:3], [1136.0, 147.0, None])

    def test_a_slash_with_two_full_codes_is_two_rows(self):
        self.assertEqual(split_codes('D-48 A/ET-48 A'),
                         [('D-48A', False), ('ET-48A', False)])

    def test_a_slash_with_a_bare_suffix_is_two_rows(self):
        self.assertEqual(split_codes('D-42F / H'),
                         [('D-42F', False), ('D-42H', False)])

    def test_any_other_slash_stays_one_ambiguous_row(self):
        for code in ('B-6/7', 'A/B/C', 'D-1/', '/D-2', 'D-5 / 12'):
            self.assertEqual(split_codes(code), [(code, True)], code)
        self.assertEqual(split_codes('D-48 HEAVY'), [('D-48 HEAVY', False)])

    def test_the_slash_row_in_a_sheet_becomes_two_lines(self):
        kinds = ['code', 'thickness'] + ['finish'] * 6
        text = ('D-48 A/ET-48 A\tNor\t1\t2\t3\t4\t5\t6\n'
                'D-11\tNor\t7\t8\t9\t10\t11\t12\n')
        rows = parse_paste(text, kinds)
        self.assertEqual([r['code'] for r in rows],
                         ['D-48A', 'ET-48A', 'D-11'])
        self.assertEqual(rows[0]['rates'], rows[1]['rates'])
        self.assertEqual(len(rows[0]['rates']), 6)


@tagged('post_install', '-at_install')
# The product is "ZT-6", not "B-6": the Chawla import already carries a real
# B-6, and two products with one code is (rightly) an ambiguous match.
class TestVendorRateLists(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.premium = env['res.partner'].create({'name': 'Premium (test)'})
        cls.other = env['res.partner'].create({'name': 'Other (test)'})
        finish_attr = env.ref('aw_fenestration_core.aw_attribute_finish')
        thick_attr = env.ref('aw_fenestration_core.aw_attribute_thickness')
        cls.finishes = finish_attr.value_ids[:3]
        cls.standard = env.ref(
            'aw_fenestration_core.aw_attr_val_thickness_standard')
        cls.product = env['product.template'].create({
            'name': 'ZT-6', 'default_code': 'ZT-6',
            'categ_id': env.ref(
                'aw_fenestration_core.product_category_profiles').id,
            'attribute_line_ids': [
                (0, 0, {'attribute_id': thick_attr.id,
                        'value_ids': [(6, 0, cls.standard.ids)]}),
                (0, 0, {'attribute_id': finish_attr.id,
                        'value_ids': [(6, 0, cls.finishes.ids)]}),
            ]})
        columns = [
            (0, 0, {'sequence': 10, 'kind': 'code', 'header': 'SEC.NO.'}),
            (0, 0, {'sequence': 20, 'kind': 'thickness'}),
            (0, 0, {'sequence': 30, 'kind': 'series'})]
        for index, finish in enumerate(cls.finishes):
            columns.append((0, 0, {
                'sequence': 40 + index, 'kind': 'finish',
                'header': finish.name, 'finish_id': finish.id}))
        cls.layout = env['aw.vendor.layout'].create({
            'vendor_id': cls.premium.id, 'column_ids': columns,
            'thickness_alias_ids': [(0, 0, {
                'alias': 'NOR', 'thickness_id': cls.standard.id})]})

    def _list(self, day, text):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.premium.id, 'date': day, 'paste_text': text})
        rate_list.action_parse_paste()
        return rate_list

    def _rates(self, vendor=None):
        return self.env['aw.profile.rate'].search([
            ('product_tmpl_id', '=', self.product.id),
            ('vendor_id', '=', (vendor or self.premium).id)])

    def test_paste_matches_and_applies_one_rate_per_finish(self):
        rate_list = self._list(date(2026, 4, 3), 'ZT-6  NOR  136 147 137')
        line = rate_list.line_ids
        self.assertEqual(line.product_tmpl_id, self.product)
        self.assertEqual(line.thickness_id, self.standard)
        self.assertFalse(line.problem)
        rate_list.action_apply()
        rates = self._rates()
        self.assertEqual(len(rates), 3)
        self.assertEqual(set(rates.mapped('date_from')), {date(2026, 4, 3)})
        self.assertEqual(sorted(rates.mapped('price')), [136.0, 137.0, 147.0])
        self.assertEqual(rate_list.state, 'applied')

    def test_a_newer_list_closes_the_old_line_the_day_before(self):
        self._list(date(2026, 4, 3), 'ZT-6  NOR  136 147 137').action_apply()
        # only the first finish changes; empty cells create nothing
        self._list(date(2026, 10, 20), 'ZT-6  NOR  140 - -').action_apply()
        natural = self.finishes[0]
        rates = self._rates().filtered(lambda r: r.finish_id == natural)
        old = rates.filtered(lambda r: r.date_from == date(2026, 4, 3))
        self.assertEqual(old.date_to, date(2026, 10, 19))
        look = self.env['aw.profile.rate']._rate_for
        self.assertEqual(look(self.product, self.standard, natural,
                              date(2026, 10, 10), self.premium).price, 136.0)
        self.assertEqual(look(self.product, self.standard, natural,
                              date(2026, 10, 25), self.premium).price, 140.0)
        # the other finishes were not touched
        self.assertEqual(len(self._rates()), 4)

    def test_another_vendors_rows_are_never_returned(self):
        self._list(date(2026, 4, 3), 'ZT-6  NOR  136 147 137').action_apply()
        rate, level = self.env['aw.profile.rate']._rate_lookup(
            self.product, self.standard, self.finishes[0],
            date(2026, 5, 1), self.other)
        self.assertFalse(rate)
        self.assertFalse(self.env['aw.profile.rate']._rate_for(
            self.product, self.standard, self.finishes[0],
            date(2026, 5, 1), self.env['res.partner']))

    def test_the_fallback_level_is_reported(self):
        Rate = self.env['aw.profile.rate']
        Rate.create({
            'product_tmpl_id': self.product.id, 'vendor_id': self.premium.id,
            'thickness_id': self.standard.id, 'finish_id': False,
            'price': 99.0, 'date_from': date(2026, 1, 1)})
        rate, level = Rate._rate_lookup(
            self.product, self.standard, self.finishes[0],
            date(2026, 5, 1), self.premium)
        self.assertEqual((rate.price, level), (99.0, 'thickness'))

    def test_an_unmatched_row_is_not_applied_and_the_pick_is_remembered(self):
        rate_list = self._list(date(2026, 4, 3), 'ZZ-9  NOR  1 2 3')
        self.assertTrue(rate_list.line_ids.problem)
        rate_list.action_apply()
        self.assertFalse(self.env['aw.profile.rate'].search_count(
            [('vendor_id', '=', self.premium.id),
             ('source_note', '=', rate_list.name),
             ('price', 'in', (1.0, 2.0, 3.0))]))
        # a plain pick matches the row but remembers nothing: an alias is
        # only made by Match to product, with its tick (see test_rates_match)
        second = self._list(date(2026, 5, 1), 'ZZ-9  NOR  1 2 3')
        second.line_ids.product_tmpl_id = self.product
        self.assertFalse(self.env['aw.vendor.alias'].search_count([
            ('vendor_id', '=', self.premium.id), ('code_norm', '=', 'ZZ9')]))
        self.env['aw.vendor.alias'].create({
            'vendor_id': self.premium.id, 'code': 'ZZ-9',
            'product_tmpl_id': self.product.id})
        third = self._list(date(2026, 6, 1), 'zz 9  NOR  1 2 3')
        self.assertEqual(third.line_ids.product_tmpl_id, self.product)

    def _rates_of(self, rate_list):
        return self.env['aw.profile.rate'].search(
            [('rate_list_id', '=', rate_list.id)])

    def test_apply_marks_its_rates_with_the_list(self):
        rate_list = self._list(date(2026, 4, 3), 'ZT-6\tNOR\t\t136\t147\t137')
        rate_list.action_apply()
        self.assertEqual(len(self._rates_of(rate_list)), 3)

    def test_reapply_deletes_only_this_lists_rates_and_reports(self):
        # two lists, one name: Re-apply on one must not touch the other
        first = self._list(date(2026, 4, 3), 'ZT-6\tNOR\t\t136\t147\t137')
        first.action_apply()
        second = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.premium.id, 'date': date(2026, 4, 3),
            'note': 'second section', 'paste_text': 'ZZ-1\tNOR\t\t1\t2\t3'})
        second.action_parse_paste()
        self.assertEqual(first.name, second.name)
        self.assertNotEqual(first.display_name, second.display_name)
        self.assertIn('second section', second.display_name)
        first.line_ids.write({'rate_1': 200.0})
        action = first.action_reapply()
        self.assertIn('3 old rate(s) deleted', action['params']['message'])
        self.assertEqual(len(self._rates_of(first)), 3)
        self.assertIn(200.0, self._rates_of(first).mapped('price'))
        self.assertEqual(first.state, 'applied')

    def _duplicate_finish_columns(self):
        """The third column now maps to the first column's finish."""
        third = self.layout.column_ids.filtered(
            lambda c: c.kind == 'finish')[2]
        third.finish_id = self.finishes[0]

    def test_two_columns_for_one_finish(self):
        self._duplicate_finish_columns()
        # a second profile for the second row: the same product, thickness
        # and finish twice with other prices is a hard stop in a paste
        self._profile('ZT-7', self.finishes)
        rate_list = self._list(
            date(2026, 4, 3),
            'ZT-6\tNOR\t\t100\t5\t100\n'     # equal: one rate
            'ZT-7\tNOR\t\t-\t6\t120')        # only one has a number
        rate_list.action_apply()
        # each row writes the shared finish once, never twice
        by_row = rate_list.line_ids.sorted('sequence')
        self.assertEqual(by_row[0].cells_conflict, 0)
        self.assertEqual(by_row[1].cells_conflict, 0)
        self.assertEqual(by_row[0].cells_applied, 2)
        self.assertEqual(by_row[1].cells_applied, 2)
        self.assertEqual(rate_list.conflict_count, 0)

    def test_differing_numbers_write_no_rate_and_say_so(self):
        self._duplicate_finish_columns()
        rate_list = self._list(
            date(2026, 4, 3), 'ZT-6\tNOR\t\t959\t7\t1120')
        rate_list.action_apply()
        line = rate_list.line_ids
        self.assertEqual(line.status_code, 'conflict')
        self.assertEqual(line.cells_conflict, 1)
        self.assertIn('959', line.detail)
        self.assertIn('1120', line.detail)
        self.assertIn('both map to', line.detail)
        self.assertEqual(line.cells_applied, 1)       # the other finish only
        self.assertNotIn(959.0, self._rates_of(rate_list).mapped('price'))
        self.assertNotIn(1120.0, self._rates_of(rate_list).mapped('price'))
        self.assertEqual(rate_list.conflict_count, 1)

    def test_set_to_draft_removes_rates_and_keeps_lines(self):
        rate_list = self._list(
            date(2026, 4, 3), 'ZT-6\tNOR\t\t136\t147\t137')
        rate_list.action_apply()
        other = self._list(date(2026, 5, 1), 'ZT-6\tNOR\t\t1\t2\t3')
        other.action_apply()
        lines = rate_list.line_ids
        rate_list.action_set_to_draft()
        self.assertEqual(rate_list.state, 'draft')
        self.assertEqual(rate_list.line_ids, lines)
        self.assertFalse(self._rates_of(rate_list))
        self.assertEqual(len(self._rates_of(other)), 3)
        self.assertEqual(lines.cells_applied, 0)
        with self.assertRaises(UserError):
            rate_list.action_set_to_draft()

    def test_grid_is_editable_on_a_draft_and_follows_the_state(self):
        rate_list = self._list(
            date(2026, 4, 3), 'ZT-6\tNOR\t\t136\t147\t137\nQQ-1\tNOR\t\t4\t5\t6')
        self.assertTrue(rate_list.grid_editable)
        self.assertTrue(all(rate_list.line_ids.mapped('grid_editable')))
        rate_list.action_apply()
        # applied: the list takes no new rows, matched rows are read only,
        # the unmatched one can still be fixed
        self.assertFalse(rate_list.grid_editable)
        matched = rate_list.line_ids.filtered('product_tmpl_id')
        unmatched = rate_list.line_ids - matched
        self.assertFalse(matched.grid_editable)
        self.assertTrue(unmatched.grid_editable)
        # set to draft: everything is editable again, no refresh needed
        rate_list.action_set_to_draft()
        self.assertTrue(rate_list.grid_editable)
        self.assertTrue(all(rate_list.line_ids.mapped('grid_editable')))
        rate_list.action_apply()
        self.assertFalse(rate_list.grid_editable)

    def test_a_cell_changed_after_set_to_draft_is_stored(self):
        rate_list = self._list(date(2026, 4, 3), 'ZT-6\tNOR\t\t136\t147\t137')
        rate_list.action_apply()
        rate_list.action_set_to_draft()
        line = rate_list.line_ids
        # what the grid sends when a cell is edited
        line.write({'rate_1': 150.0})
        line.invalidate_recordset()
        self.env.invalidate_all()
        self.assertEqual(
            self.env['aw.vendor.rate.list.line'].search_read(
                [('list_id', '=', rate_list.id)], ['rate_1'])[0]['rate_1'],
            150.0)
        rate_list.action_apply()
        self.assertIn(150.0, self._rates_of(rate_list).mapped('price'))

    def test_reapply_needs_an_applied_list(self):
        draft = self._list(date(2026, 4, 3), 'ZT-6\tNOR\t\t1\t2\t3')
        with self.assertRaises(UserError):
            draft.action_reapply()

    def test_rematch_on_an_applied_list_leaves_rates_and_matched_rows(self):
        rate_list = self._list(
            date(2026, 4, 3), 'ZT-6\tNOR\t\t1\t2\t3\nQQ-1\tNOR\t\t4\t5\t6')
        rate_list.action_apply()
        rates = self._rates_of(rate_list)
        matched = rate_list.line_ids.filtered(
            lambda l: l.product_tmpl_id == self.product)
        rate_list.action_rematch()
        self.assertEqual(self._rates_of(rate_list), rates)
        self.assertEqual(matched.product_tmpl_id, self.product)
        self.assertEqual(rate_list.unmatched_count, 1)

    def test_free_text_thickness_must_resolve_or_the_row_is_flagged(self):
        rate_list = self._list(date(2026, 4, 3), 'ZT-6\tNOR\t\t1\t2\t3')
        line = rate_list.line_ids
        line.write({'thickness_text': '9.9MM'})
        self.assertIn('Unknown thickness', line.problem)
        self.assertFalse(self.env['aw.vendor.thickness.alias'].search(
            [('alias', '=', '9.9MM')]))          # nothing created from an edit
        line.write({'thickness_text': 'NOR'})
        self.assertFalse(line.problem)

    def test_backfill_links_rates_only_where_the_name_is_unique(self):
        unique = self._list(date(2026, 4, 3), 'ZT-6\tNOR\t\t1\t2\t3')
        unique.action_apply()
        rates = self._rates_of(unique)
        self.env.flush_all()          # raw SQL below must see the rates
        self.env.cr.execute(
            "UPDATE aw_profile_rate SET rate_list_id = NULL WHERE id IN %s",
            (tuple(rates.ids),))
        rates.invalidate_recordset()
        self.env['aw.profile.rate']._backfill_rate_list_ids()
        rates.invalidate_recordset()
        self.assertEqual(rates.rate_list_id, unique)
        # a second list with the same name makes the link ambiguous
        self._list(date(2026, 4, 3), 'ZZ-1\tNOR\t\t1\t2\t3')
        self.env.flush_all()          # raw SQL below must see the rates
        self.env.cr.execute(
            "UPDATE aw_profile_rate SET rate_list_id = NULL WHERE id IN %s",
            (tuple(rates.ids),))
        rates.invalidate_recordset()
        self.env['aw.profile.rate']._backfill_rate_list_ids()
        rates.invalidate_recordset()
        self.assertFalse(rates.rate_list_id)

    def test_fill_from_current_rates_prefills_the_series(self):
        first = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.premium.id, 'date': date(2026, 4, 3),
            'paste_text': 'ZT-6\tNOR\tDG.SERIES\t136\t147\t137'})
        first.action_parse_paste()
        first.action_apply()
        again = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.premium.id, 'date': date(2026, 11, 1),
            'fill_series': 'DG.SERIES'})
        again.action_fill_from_current()
        self.assertEqual(len(again.line_ids), 1)
        line = again.line_ids
        self.assertEqual(
            sorted([line.rate_1, line.rate_2, line.rate_3]),
            [136.0, 137.0, 147.0])


    def _row_list(self, text, day=date(2026, 4, 3)):
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': self.premium.id, 'date': day, 'paste_text': text})
        rate_list.action_parse_paste()
        return rate_list

    def _profile(self, code, finishes, thicknesses=None):
        env = self.env
        return env['product.template'].create({
            'name': code, 'default_code': code,
            'categ_id': env.ref(
                'aw_fenestration_core.product_category_profiles').id,
            'attribute_line_ids': [
                (0, 0, {'attribute_id': env.ref(
                    'aw_fenestration_core.aw_attribute_thickness').id,
                    'value_ids': [(6, 0, (thicknesses
                                          or self.standard).ids)]}),
                (0, 0, {'attribute_id': env.ref(
                    'aw_fenestration_core.aw_attribute_finish').id,
                    'value_ids': [(6, 0, finishes.ids)]})]})

    def test_each_state_is_counted_worded_and_clears_after_a_rematch(self):
        env = self.env
        thick_attr = env.ref('aw_fenestration_core.aw_attribute_thickness')
        other_thickness = (thick_attr.value_ids - self.standard)[:1]
        self.env['aw.vendor.thickness.alias'].create({
            'layout_id': self.layout.id, 'alias': 'X16',
            'thickness_id': other_thickness.id})
        thin = self._profile('ZT-TH1', self.finishes)
        self._profile('UN-1', self.finishes)
        fin = self._profile('FI-1', self.finishes[:1])
        rows = '\n'.join([
            'ZZ-1\tNOR\t\t1\t2\t3',        # no product
            'ZT-TH1\tX16\t\t1\t2\t3',        # thickness not on the product
            'UN-1\tQQQ\t\t1\t2\t3',        # no such thickness at all
            'FI-1\tNOR\t\t1\t2\t3',        # finishes not on the product
            'ZT-6\tNOR\t\t136\t147\t137'])  # ready
        counts = {m: env[m].search_count([]) for m in (
            'product.template', 'product.product',
            'product.attribute.value')}
        rate_list = self._row_list(rows)
        by_code = {l.code: l for l in rate_list.line_ids}
        self.assertEqual(
            rate_list.need_summary,
            '1 need a product, 1 need a thickness, 1 unknown thickness, '
            '1 need a finish')
        self.assertEqual(by_code['ZZ-1'].need_text,
                         'No product ZZ-1: create it in Products, then '
                         'Re-match')
        self.assertEqual(
            by_code['ZT-TH1'].need_text,
            'ZT-TH1 has no thickness %s: add it on the product (Attributes & '
            'Variants), then Re-match' % other_thickness.name)
        self.assertEqual(by_code['UN-1'].need, 'unknown_thickness')
        self.assertIn("Unknown thickness 'QQQ'", by_code['UN-1'].need_text)
        self.assertEqual(
            by_code['FI-1'].need_text,
            'FI-1 has no finish %s, %s: add them on the product, then '
            'Re-match' % (self.finishes[1].name, self.finishes[2].name))
        self.assertFalse(by_code['ZT-6'].need)
        self.assertEqual(rate_list.action_show_need_product()['domain'][1],
                         ('need', '=', 'product'))

        rate_list.action_apply()
        # ZT-6 in full, FI-1's one existing finish; nothing else written
        self.assertEqual(len(self._rates_for(self.product)), 3)
        self.assertEqual(len(self._rates_for(fin)), 1)
        self.assertFalse(self._rates_for(thin))
        self.assertEqual(by_code['FI-1'].status_code, 'needs_finish')
        self.assertTrue(by_code['FI-1'].detail.startswith('FI-1 has no finish'))
        # Apply created no product, variant or attribute value
        for model, count in counts.items():
            self.assertEqual(env[model].search_count([]), count, model)

        # fix the products, Re-match turns the rows applicable, Re-apply
        zz = self._profile('ZZ-1', self.finishes)
        fin.write({'attribute_line_ids': [(0, 0, {
            'attribute_id': env.ref(
                'aw_fenestration_core.aw_attribute_finish').id,
            'value_ids': [(4, f.id) for f in self.finishes[1:]]})]})
        rate_list.action_rematch()
        self.assertFalse(by_code['ZZ-1'].need)
        self.assertEqual(by_code['ZZ-1'].product_tmpl_id, zz)
        self.assertFalse(by_code['FI-1'].need)
        self.assertEqual(
            rate_list.need_summary,
            '0 need a product, 1 need a thickness, 1 unknown thickness, '
            '0 need a finish')
        rate_list.action_reapply()
        self.assertEqual(len(self._rates_for(zz)), 3)
        self.assertEqual(len(self._rates_for(fin)), 3)
        self.assertEqual(len(self._rates_for(self.product)), 3)

    def _rates_for(self, product):
        return self.env['aw.profile.rate'].search([
            ('product_tmpl_id', '=', product.id),
            ('vendor_id', '=', self.premium.id)])


@tagged('post_install', '-at_install')
class TestPremiumSeed(TransactionCase):

    def test_seed_creates_what_is_missing_and_only_once(self):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('aw_fenestration.premium_layout_seeded', False)
        Layout = self.env['aw.vendor.layout']
        report = Layout._seed_premium_layout()
        self.assertTrue(report['partner'])
        layout = Layout.search([('vendor_id.name', 'ilike', 'premium')])
        if 'created' in (report['layout'] or ''):
            kinds = layout.column_ids.sorted('sequence').mapped('kind')
            self.assertEqual(kinds[:3], ['code', 'thickness', 'series'])
            self.assertEqual(len(kinds), 10)
            self.assertIn('BRO', report['finishes_unmapped'])
            self.assertTrue(
                any(a.startswith('NOR') for a in report['thickness_set']))
        # a second run does nothing
        self.assertIsNone(Layout._seed_premium_layout())


@tagged('post_install', '-at_install')
class TestLayoutWithoutRateColumns(TransactionCase):

    def test_the_error_says_the_layout_has_no_rate_columns(self):
        vendor = self.env['res.partner'].create({'name': 'No rates (test)'})
        self.env['aw.vendor.layout'].create({
            'vendor_id': vendor.id, 'column_ids': [
                (0, 0, {'sequence': 10, 'kind': 'code', 'header': 'Section #'}),
                (0, 0, {'sequence': 20, 'kind': 'thickness'}),
                (0, 0, {'sequence': 30, 'kind': 'series'})]})
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': vendor.id,
            'paste_text': 'B-6\tNOR\t\t136\t147'})
        self.assertIn('no rate columns', rate_list.columns_legend)
        with self.assertRaises(Exception) as caught:
            rate_list.action_parse_paste()
        self.assertIn('no rate columns', str(caught.exception))
        self.assertIn('Section #', str(caught.exception))

    def test_a_rate_column_without_a_finish_is_read_but_not_applied(self):
        vendor = self.env['res.partner'].create({'name': 'Half mapped (test)'})
        finish = self.env.ref(
            'aw_fenestration_core.aw_attribute_finish').value_ids[0]
        layout = self.env['aw.vendor.layout'].create({
            'vendor_id': vendor.id, 'column_ids': [
                (0, 0, {'sequence': 10, 'kind': 'code'}),
                (0, 0, {'sequence': 20, 'kind': 'thickness'}),
                (0, 0, {'sequence': 30, 'kind': 'series'}),
                (0, 0, {'sequence': 40, 'kind': 'finish', 'header': 'DULL',
                        'finish_id': finish.id}),
                (0, 0, {'sequence': 50, 'kind': 'finish', 'header': 'BRO'})]})
        rate_list = self.env['aw.vendor.rate.list'].create({
            'vendor_id': vendor.id,
            'paste_text': 'ZZ-1\tNOR\t\t100\t110'})
        rate_list.action_parse_paste()
        line = rate_list.line_ids
        self.assertEqual((line.rate_1, line.rate_2), (100.0, 110.0))
        self.assertIn('BRO', rate_list.columns_legend)
        self.assertIn('no finish set', rate_list.columns_legend)
        self.assertEqual(len(layout._finish_columns()), 2)


@tagged('post_install', '-at_install')
class TestChawlaSeed(TransactionCase):

    def test_seed_makes_the_layout_once(self):
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('aw_fenestration.chawla_layout_seeded', False)
        Layout = self.env['aw.vendor.layout']
        report = Layout._seed_chawla_layout()
        self.assertTrue(report['partner'])
        if 'created' in (report['layout'] or ''):
            layout = Layout.search(
                [('vendor_id.name', 'ilike', 'chawla')], limit=1)
            columns = layout.column_ids.sorted('sequence')
            self.assertEqual(
                columns.mapped('kind')[:2], ['code', 'thickness'])
            self.assertEqual(
                columns.mapped('header')[2:],
                ['natural', 'h23_pc_ral', 'brown_pc_sahara',
                 'black_multi_ss_dull', 'designer', 'c_shine'])
            self.assertEqual(columns.mapped('header')[:2],
                             ['profile_code', 'thickness'])
            self.assertEqual(len(report['finishes_set']), 6)
            self.assertEqual(report['finishes_unmapped'], [])
            self.assertIn('Nor -> Normal', report['thickness_set'])
        self.assertIsNone(Layout._seed_chawla_layout())
