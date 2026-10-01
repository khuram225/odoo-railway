# -*- coding: utf-8 -*-
"""One screen over the three panel-option tables (Part 2, revised).

Fly screens, infills and Georgian bars are three models because they
behave differently -- a fly screen has a mechanism and a pull, an infill
is glazed or not, a grid has a pattern kind -- but to the person
maintaining them they are one list: "what can go in a panel". Three
menu items for three short lists was three places to look.

This is an UNMANAGED model (`_auto = False`) over a SQL view that unions
the three. That choice is worth stating, because the alternatives are
worse: a shared mixin would need all three tables migrated into one and
would throw away the per-kind fields; copying rows into a fourth table
would need keeping in step for ever. A read-only union is neither, and
it cannot drift -- there is nothing in it to drift.

What it costs: no Many2many on a SQL view, so `available_series_ids`
stays on the three real models, and a row opens its REAL record through
`action_open()` rather than being edited here. Forms stay per model,
which is what the brief asks for anyway.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

# kind -> (model, label). The order is the order the list groups in.
OPTION_MODELS = {
    'mesh': ('aw.mesh.type', 'Fly screen'),
    'infill': ('aw.infill.type', 'Infill / add-on'),
    'grid': ('aw.grid.pattern', 'Georgian bars'),
}


class AwPanelOption(models.Model):
    _name = 'aw.panel.option'
    _description = 'Fenestration Panel Option'
    _auto = False
    _order = 'kind, sequence, name'

    name = fields.Char(readonly=True)
    code = fields.Char(readonly=True)
    kind = fields.Selection([
        ('mesh', 'Fly screen'),
        ('infill', 'Infill / add-on'),
        ('grid', 'Georgian bars'),
    ], readonly=True, string='Type')
    sequence = fields.Integer(readonly=True)
    active = fields.Boolean(readonly=True)
    # Enough detail to tell two rows apart without opening either:
    # a fly screen's mechanism, an infill's kind, a grid's pattern.
    detail = fields.Char(readonly=True, string='Detail')
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)

    @property
    def _table_query(self):
        """The union, as one SELECT.

        The id has to be unique across all three tables, so each kind is
        offset into its own band rather than using the raw id: two
        tables both having a row 1 would otherwise collide and the list
        would show one of them twice. `res_id` keeps the real id for
        action_open().

        `name` is selected as a plain column, NOT `name->>'en_US'`:
        these are `fields.Char` without `translate=True`, so the column
        is varchar rather than jsonb and the json operator would fail
        at registry load. Add `translate=True` to any of them and this
        has to change with it.
        """
        return """
            SELECT (1000000 + m.id) AS id, m.id AS res_id,
                   'aw.mesh.type' AS res_model, 'mesh' AS kind,
                   m.name AS name, m.code AS code,
                   m.sequence AS sequence, m.active AS active,
                   m.mechanism AS detail
              FROM aw_mesh_type m
             UNION ALL
            SELECT (2000000 + i.id) AS id, i.id AS res_id,
                   'aw.infill.type' AS res_model, 'infill' AS kind,
                   i.name AS name, i.code AS code,
                   i.sequence AS sequence, i.active AS active,
                   i.kind AS detail
              FROM aw_infill_type i
             UNION ALL
            SELECT (3000000 + g.id) AS id, g.id AS res_id,
                   'aw.grid.pattern' AS res_model, 'grid' AS kind,
                   g.name AS name, g.code AS code,
                   g.sequence AS sequence, g.active AS active,
                   g.kind AS detail
              FROM aw_grid_pattern g
        """

    def action_open(self):
        """Open the real record this row stands for."""
        self.ensure_one()
        if self.res_model not in {m for m, _label in OPTION_MODELS.values()}:
            raise UserError(_("Unknown panel option type."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.name or _('Panel Option'),
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    @api.model
    def _available_for_series(self, series):
        """The option records offered on `series`, per kind.

        One rule for all three, applied where the library and the Panel
        tab read them, so "available on" cannot mean one thing for fly
        screens and another for bars. Empty `available_series_ids` means
        every system -- the common case, and the safe default.
        """
        out = {}
        for kind, (model, _label) in OPTION_MODELS.items():
            records = self.env[model].search([])
            if series:
                records = records.filtered(
                    lambda r, s=series: (not r.available_series_ids
                                         or s in r.available_series_ids))
            out[kind] = records
        return out
