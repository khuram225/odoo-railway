# -*- coding: utf-8 -*-
"""Save a design end to end, which is where the explosion actually runs.

The regression this exists for: `self._aw_spans = {}` in the explosion
engine. Odoo 19 records use `__slots__`, so a record cannot carry
ad-hoc attributes, and every single save of every design failed with
"'aw.design' object has no attribute '_aw_spans'".

It would have shown on the first save of anything. No static check
existed for it at the time, and no test called `save_layout` at all --
the round-trip test asserts the HEADER survives a save, which it does
by taking the same payload straight back, and never looks at what the
explosion did underneath.

So this test is deliberately about the WALK: more than one panel, more
than one row, so dividers and transoms are both generated and the span
bookkeeping is exercised rather than skipped.
"""
import unittest

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDesignSave(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A family with at least one active system, which is what the
        # save path needs: _resolve_system() picks the system from the
        # family once the panels are known.
        cls.family = cls.env['aw.window.family'].search([]).filtered(
            lambda f: f.series_ids.filtered('active').filtered(
                lambda s: s.leaf_type_ids))[:1]
        if not cls.family:
            raise unittest.SkipTest(
                "No glazing family with a configured profile system")
        cls.series = cls.family.series_ids.filtered('active').filtered(
            lambda s: s.leaf_type_ids)[0]
        cls.leaf_type = cls.series.leaf_type_ids[0]
        cls.design = cls.env['aw.design'].create({
            'name': 'SAVE1',
            'window_series_id': cls.series.id,
            'family_id': cls.family.id,
            'width_mm': 2400.0,
            'height_mm': 1800.0,
        })

    def _panels(self):
        """Every leaf that is a panel, i.e. not a container."""
        found = []

        def walk(rows):
            for row in rows:
                for leaf in row.leaf_ids:
                    if leaf.child_row_ids:
                        walk(leaf.child_row_ids)
                    else:
                        found.append(leaf)

        walk(self.design.row_ids)
        return found

    def _payload(self):
        """Two rows, two panels in the first: a divider AND a transom."""
        leaf = {'width_mm': 1200.0, 'leaf_type_id': self.leaf_type.id}
        return {
            'header': self.design.get_configurator_data()['header'],
            'rows': [
                {'height_mm': 900.0, 'leaves': [dict(leaf), dict(leaf)]},
                {'height_mm': 900.0,
                 'leaves': [dict(leaf, width_mm=2400.0)]},
            ],
        }

    def test_save_layout_runs_the_explosion(self):
        """The save must complete and leave the design consistent.

        This is the assertion that would have caught `_aw_spans`:
        save_layout() calls _explode(), and the explosion touched the
        span bookkeeping on the very first divider it walked past.
        """
        self.design.save_layout(self._payload())

        self.assertEqual(len(self.design.row_ids), 2)
        panels = self._panels()
        self.assertEqual(len(panels), 3)
        # Numbering is the server's job and happens during the save.
        self.assertEqual(
            sorted(panel.panel_no for panel in panels), [1, 2, 3],
            "Panels were not renumbered during save_layout.")

    def test_saving_twice_is_stable(self):
        """A second save must not double anything up.

        The explosion clears and rebuilds, so two identical saves have
        to produce identical output. A leak in that would show as a
        BOM that grows every time somebody presses Save.
        """
        self.design.save_layout(self._payload())
        first = len(self.design.bom_line_ids)
        self.design.save_layout(self._payload())
        self.assertEqual(
            len(self.design.bom_line_ids), first,
            "Re-saving changed the BOM line count; the explosion is "
            "not clearing what it replaces.")

    def test_checks_are_regenerated(self):
        """Checks belong to the layout that is there now."""
        self.design.save_layout(self._payload())
        before = self.design.check_line_ids.ids
        self.design.save_layout(self._payload())
        self.assertFalse(
            set(before) & set(self.design.check_line_ids.ids),
            "Old check rows survived a re-save.")
