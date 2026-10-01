from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "pp_print_core")
class TestPrintMasters(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.paper = cls.env["product.template"].create({
            "name": "Art paper 115 gsm 25x36",
            "print_material_type": "paper",
            "print_gsm": 115, "print_width_in": 25, "print_height_in": 36,
            "print_units_per_pack": 500,
        })
        cls.env["print.material.price"].create([
            {"product_tmpl_id": cls.paper.id, "date_from": date(2026, 1, 1), "basis": "kg", "price": 560},
            {"product_tmpl_id": cls.paper.id, "date_from": date(2026, 9, 1), "basis": "kg", "price": 590},
        ])

    def test_kg_per_sheet(self):
        # 25 x 36 in x 0.00064516 x 115 / 1000
        self.assertAlmostEqual(self.paper.print_kg_per_sheet, 25 * 36 * 0.00064516 * 115 / 1000, places=6)
        # Same basis as the costing sheet's W x H x gsm / 3100 / 500 (within 0.01 %)
        self.assertAlmostEqual(self.paper.print_kg_per_sheet, 25 * 36 * 115 / 3100 / 500, places=4)

    def test_effective_dated_price(self):
        old = self.paper.print_costs_on(date(2026, 6, 30))
        new = self.paper.print_costs_on(date(2026, 9, 30))
        self.assertEqual(old["price"], 560)
        self.assertEqual(new["price"], 590)
        self.assertAlmostEqual(new["cost_per_sheet"], 590 * self.paper.print_kg_per_sheet, places=6)
        self.assertEqual(self.paper.print_costs_on(date(2025, 12, 31))["price"], 0.0)

    def test_pack_price(self):
        board = self.env["product.template"].create({
            "name": "Board 2 mm", "print_material_type": "board", "print_gsm": 1200,
            "print_width_in": 20, "print_height_in": 30, "print_units_per_pack": 10,
        })
        self.env["print.material.price"].create({"product_tmpl_id": board.id, "date_from": date(2026, 1, 1), "basis": "pack", "price": 950})
        self.assertAlmostEqual(board.print_costs_on(date(2026, 9, 1))["cost_per_sheet"], 95.0)

    def test_factor_group_min(self):
        group = self.env["print.factor.group"].create({"code": "T1", "name": "Test speed", "calc_method": "min"})
        run = self.env["print.factor"].create({"group_id": group.id, "code": "RUN", "name": "Run speed", "input_variable": "print_total_per_run",
                                              "point_ids": [(0, 0, {"input_value": 1000, "output_value": 5000}),
                                                            (0, 0, {"input_value": 2000, "output_value": 6863})]})
        self.env["print.factor"].create({"group_id": group.id, "code": "GSM", "name": "Gsm speed", "input_variable": "grammage",
                                         "point_ids": [(0, 0, {"input_value": 150, "output_value": 9000}),
                                                       (0, 0, {"input_value": 300, "output_value": 6000})]})
        self.assertAlmostEqual(run.value_at(1500), 5931.5)
        self.assertEqual(run.value_at(500), 5000)       # flat below the first point
        self.assertEqual(run.value_at(9000), 6863)      # flat above the last point
        value, how = group.evaluate({"print_total_per_run": 2000, "grammage": 300})
        self.assertEqual(value, 6000)                   # grammage limits the speed
        self.assertIn("GSM", how)

    def test_workcenter_rates(self):
        role = self.env["print.labour.role"].create({"code": "OP", "name": "Operator",
                                                     "rate_ids": [(0, 0, {"date_from": date(2026, 1, 1), "rate_hr": 450})]})
        group = self.env["print.cost.group"].create({"code": "OFF", "name": "Offset print"})
        wc = self.env["print.workcenter"].create({
            "code": "SM74", "name": "Four-colour press", "workcenter_type": "offset", "cost_group_id": group.id,
            "crew_ids": [(0, 0, {"role_id": role.id, "count": 2})],
            "rate_ids": [(0, 0, {"date_from": date(2026, 1, 1), "direct_rate_hr": 1800, "indirect_rate_hr": 3000})],
        })
        self.assertEqual(wc.crew_rate_on(date(2026, 9, 1)), 900)
        self.assertEqual(wc.rate_on(date(2026, 9, 1)).direct_rate_hr, 1800)
        self.assertFalse(wc.rate_on(date(2025, 1, 1)))

    def test_seed_data(self):
        self.assertEqual(self.env["print.product.group"].search_count([]), 6)
        self.assertGreaterEqual(self.env["print.base.product"].search_count([]), 23)
        imp = self.env["print.imposition"].search([("code", "=", "B-008L")])
        self.assertEqual(imp.pages_per_sheet, 8)
