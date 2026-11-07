# -*- coding: utf-8 -*-
"""Open the configurator, save without touching anything, and assert the
design is unchanged.

The regression this exists for: save_layout wrote header fields straight
from the client payload, so any field the client did not send was
written as empty. `manual_rate` had no control in the configurator at
all and was in the save allow-list, so a hand-entered price override was
destroyed by every save -- silently, with no error and nothing on screen
to notice.

A pure round trip is the right shape for this. It needs no fixtures
beyond a design, it asserts the one property that must always hold, and
it fails for ANY field added to the allow-list later without being
loaded -- including fields nobody has thought of yet, which is what a
static list of field names cannot do.

scripts/check_configurator_header.py catches the same class statically
and runs in the pre-commit hook; this runs where there is a database.
Run with:  odoo -u aw_fenestration_design --test-enable --stop-after-init
"""
from odoo.addons.aw_fenestration_design.tests.common import (
    seeded_family_series)
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConfiguratorRoundTrip(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.series = seeded_family_series(cls.env)[1]
        cls.design = cls.env['aw.design'].create({
            'name': 'RT1',
            'window_series_id': cls.series.id,
            'width_mm': 2438.4,
            'height_mm': 1524.0,
        })

    def _header_snapshot(self):
        """Every field a save is allowed to write, read off the record."""
        design = self.design
        return {
            name: (design[name].id
                   if design._fields[name].type == 'many2one'
                   else design[name])
            for name in design.CONFIGURATOR_HEADER_FIELDS
        }

    def test_save_without_changes_keeps_every_header_field(self):
        """The core property: load, save the payload back untouched, and
        nothing about the header moves."""
        self.design.manual_rate = 123.45
        self.design.glass_part_ids = [(5, 0, 0)] + self.env[
            'aw.glass.part']._commands_from([
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0}])

        data = self.design.get_configurator_data()
        before = self._header_snapshot()

        self.design.save_layout({
            'header': data['header'], 'rows': data['rows'],
        })

        self.assertEqual(
            self._header_snapshot(), before,
            "Saving the configurator payload unchanged altered the header.")

    def test_header_field_missing_from_payload_is_not_blanked(self):
        """The actual failure mode: a hidden control sends nothing, and
        nothing must not be written as empty."""
        self.design.manual_rate = 99.0
        section = self.design.profile_section_id

        data = self.design.get_configurator_data()
        stripped = {k: v for k, v in data['header'].items()
                    if k not in ('manual_rate', 'profile_section_id')}
        self.design.save_layout({'header': stripped, 'rows': data['rows']})

        self.assertEqual(
            self.design.manual_rate, 99.0,
            "An unsent manual_rate was blanked by the save.")
        if section:
            self.assertEqual(
                self.design.profile_section_id, section,
                "An unsent profile_section_id was blanked by the save.")

    def test_explicit_clear_still_clears(self):
        """The other half: a real 'no glass' choice must still be possible
        -- sending an empty window stack clears it."""
        self.design.glass_part_ids = [(5, 0, 0)] + self.env[
            'aw.glass.part']._commands_from([
                {'kind': 'sheet', 'glass_type': 'Clear', 'thickness_mm': 6.0}])
        self.assertTrue(self.design.glass_part_ids)

        data = self.design.get_configurator_data()
        header = dict(data['header'], glass_stack=[])
        self.design.save_layout({'header': header, 'rows': data['rows']})

        self.assertFalse(
            self.design.glass_part_ids,
            "Clearing the glass stack from the header did not take effect.")
