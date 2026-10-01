from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "pp_print_core")
class TestPrintEstimate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mag = cls.env.ref("pp_print_core.bp_mag")
        cls.customer = cls.env["res.partner"].create({"name": "Test School", "is_company": True})
        cls.contact = cls.env["res.partner"].create({"name": "Admin office", "parent_id": cls.customer.id, "phone": "042-111"})
        cls.a4 = cls.env["print.format"].search([("code", "=", "A4_V")])

    def _estimate(self, **kw):
        vals = {"job_name": "Magazine", "base_product_id": self.mag.id, "partner_id": self.customer.id, "run_qty": 350}
        vals.update(kw)
        return self.env["print.estimate"].create(vals)

    def test_numbering_and_default_pages(self):
        est = self._estimate()
        self.assertTrue(est.name.startswith("E01-"))
        self.assertEqual(est.version, 1)
        self.assertEqual(est.page_ids.mapped("page_type_id.code"), ["Cover1", "Text1"])
        self.assertEqual(est.pages_label, "4 + 48")
        std = self._estimate(is_standard=True)
        self.assertTrue(std.name.startswith("S01-"))

    def test_format_size_and_override(self):
        est = self._estimate(format_id=self.a4.id)
        self.assertAlmostEqual(est.width_in, 8.27)
        est.width_in = 8.5
        self.assertAlmostEqual(est.width_in, 8.5)

    def test_new_version_keeps_number(self):
        est = self._estimate()
        action = est.action_new_version()
        v2 = self.env["print.estimate"].browse(action["res_id"])
        self.assertEqual(v2.name, est.name)
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.pages_label, est.pages_label)

    def test_copy_and_standard(self):
        est = self._estimate()
        copy = self.env["print.estimate"].browse(est.action_copy_estimate()["res_id"])
        self.assertNotEqual(copy.name, est.name)
        std = self.env["print.estimate"].browse(est.action_save_as_standard()["res_id"])
        self.assertTrue(std.is_standard and std.name.startswith("S01-") and not std.partner_id)
        new = self.env["print.estimate"].browse(std.action_use_standard()["res_id"])
        self.assertFalse(new.is_standard)
        self.assertEqual(new.template_id, std)
        with self.assertRaises(UserError):
            est.action_use_standard()

    def test_versions_warning_and_checks(self):
        est = self._estimate(run_qty=500, version_line_ids=[(0, 0, {"shift": "V1", "description": "English", "run_qty": 300}),
                                                            (0, 0, {"shift": "V2", "description": "Urdu", "run_qty": 150})])
        self.assertIn("450", est.versions_warning)
        est.version_line_ids[1].run_qty = 200
        self.assertFalse(est.versions_warning)
        with self.assertRaises(UserError):
            est.page_ids.filtered(lambda p: p.kind == "text").pages = 45
        with self.assertRaises(UserError):
            est.run_qty = 0

    def test_contact_info(self):
        est = self._estimate(contact_id=self.contact.id)
        self.assertEqual(est.phone, "042-111")
