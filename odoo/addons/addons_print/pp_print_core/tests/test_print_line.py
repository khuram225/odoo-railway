from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "pp_print_core")
class TestPrintLine(TransactionCase):
    """Reproduces a known costing-sheet job: A4 magazine, 350 copies, 44 pages 4/4 on 115 gsm 25x36,
    title 4/0 on 300 gsm card 25x36. Expected: 1,512.5 text paper sheets, 44 plates; 137.5 card sheets, 4 plates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env["ir.config_parameter"].sudo().set_param("pp_print_core.colour_strip_in", "0.2")
        env["ir.config_parameter"].sudo().set_param("pp_print_core.gap_in", "0")
        grp = env["print.cost.group"].create({"code": "OFFT", "name": "Offset test"})
        cls.sm = env["print.workcenter"].create({"code": "T-4C", "name": "Four-colour 18x25", "workcenter_type": "offset",
                                                 "cost_group_id": grp.id, "max_width_in": 18, "max_height_in": 25,
                                                 "colour_units": 4, "gripper_in": 0.4, "makeready_sheets": 100, "running_waste_pct": 2})
        cls.gto = env["print.workcenter"].create({"code": "T-2C", "name": "Two-colour 12.5x18", "workcenter_type": "offset",
                                                  "cost_group_id": grp.id, "max_width_in": 13, "max_height_in": 18.5,
                                                  "colour_units": 2, "gripper_in": 0.4, "makeready_sheets": 60})
        cls.paper = env["product.template"].create({"name": "Art 115 25x36", "print_material_type": "paper", "print_gsm": 115,
                                                    "print_width_in": 25, "print_height_in": 36, "print_caliper_micron": 99})
        env["print.material.price"].create({"product_tmpl_id": cls.paper.id, "date_from": date(2026, 1, 1), "basis": "kg", "price": 590})
        cls.card = env["product.template"].create({"name": "Card 300 25x36", "print_material_type": "card", "print_gsm": 300,
                                                   "print_width_in": 25, "print_height_in": 36, "print_caliper_micron": 305})
        cls.a4 = env["print.format"].search([("code", "=", "A4_V")])
        cls.cover = env.ref("pp_print_core.pt_cover1")
        cls.text = env.ref("pp_print_core.pt_text1")

    def _estimate(self):
        return self.env["print.estimate"].create({
            "job_name": "Magazine test", "base_product_id": self.env.ref("pp_print_core.bp_mag").id, "run_qty": 350,
            "format_id": self.a4.id, "date": date(2026, 9, 30),
            "page_ids": [(0, 0, {"page_type_id": self.cover.id, "pages": 4, "material_id": self.card.id, "sequence": 1,
                                 "colours_front": 4, "colours_back": 0, "press_id": self.gto.id,
                                 "scrap_method": "sheets", "scrap_value": 50}),
                         (0, 0, {"page_type_id": self.text.id, "pages": 44, "material_id": self.paper.id, "sequence": 2,
                                 "colours_front": 4, "colours_back": 4, "press_id": self.sm.id,
                                 "scrap_method": "copies", "scrap_value": 200})],
        })

    def test_known_job(self):
        est = self._estimate()
        cover, text = est.page_ids.sorted("sequence")
        self.assertTrue(text.calc_ok, text.calc_error)
        self.assertEqual(text.parts_used, 2)
        self.assertEqual(text.no_up, 1)
        self.assertEqual(text.pages_per_sheet, 8)
        self.assertAlmostEqual(text.sheets_per_copy, 5.5)
        self.assertAlmostEqual(text.paper_sheets, 1512.5)
        self.assertEqual(text.plates_total, 44)
        self.assertAlmostEqual(text.paper_cost, 1512.5 * 590 * 25 * 36 * 0.00064516 * 115 / 1000, places=2)
        self.assertTrue(cover.calc_ok, cover.calc_error)
        self.assertEqual(cover.parts_used, 4)
        self.assertEqual(cover.no_up, 1)
        self.assertAlmostEqual(cover.paper_sheets, 137.5)
        self.assertEqual(cover.plates_total, 4)
        self.assertAlmostEqual(cover.spine_in, 22 * 99 / 25400, places=3)
        self.assertTrue(text.calc_log_ids and cover.calc_log_ids)
        self.assertAlmostEqual(est.total_plates, 48)

    def test_recalculates_on_change_and_errors(self):
        est = self._estimate()
        text = est.page_ids.filtered(lambda p: p.kind == "text")
        text.scrap_method = "wc"
        # 11 make-readies x 100 sheets + 2 % running waste on 1,925 net
        self.assertAlmostEqual(text.print_total, 1925 + 1100 + 38.5)
        text.imposition_id = self.env["print.imposition"].search([("code", "=", "B-016L")])
        self.assertFalse(text.calc_ok)
        self.assertIn("does not fit", text.calc_error)
        self.assertIn("Text1", est.calc_warning)
        text.imposition_id = False
        text.extra_plates = 2
        self.assertEqual(text.plates_total, 46)

    def test_settings_parameters(self):
        settings = self.env["res.config.settings"].create({"print_colour_strip_in": 0.5, "print_gap_in": 0.125})
        settings.execute()
        icp = self.env["ir.config_parameter"].sudo()
        self.assertEqual(float(icp.get_param("pp_print_core.colour_strip_in")), 0.5)
        self.assertEqual(float(icp.get_param("pp_print_core.gap_in")), 0.125)
        self.assertNotIn("print_colour_strip_in", self.env["res.company"]._fields)

    def test_auto_press_and_digital(self):
        est = self._estimate()
        text = est.page_ids.filtered(lambda p: p.kind == "text")
        text.press_id = False
        self.assertEqual(text.press_used_id, self.sm)   # GTO has 2 units, text needs 4 colours
        dig = self.env["print.workcenter"].create({"code": "T-DIG", "name": "Digital", "workcenter_type": "digital",
                                                   "cost_group_id": self.sm.cost_group_id.id, "max_width_in": 13,
                                                   "max_height_in": 19, "colour_units": 4, "perfecting": True})
        text.press_id = dig
        self.assertEqual(text.plates_total, 0)
        self.assertEqual(text.passes, 1)
