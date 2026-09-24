# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # No res.company field -- backed by ir.config_parameter instead, so
    # there's no schema change on any core model. Adding a required stored
    # field to res.company (read/prefetched on EVERY request) meant a
    # window between "code deployed" and "Upgrade actually run" where any
    # real page load crashed with UndefinedColumn -- confirmed via
    # odoo-src: a plain boot never runs the schema DDL that would add the
    # column (Registry.new()/load_modules() both default
    # update_module=False, and init_models() -- the actual ALTER TABLE --
    # only runs when that's True, i.e. only for -i/-u or the Install/
    # Upgrade buttons). check_null_constraints()'s "Missing not-null
    # constraint" warning can't tell a genuinely missing column apart
    # from an existing-but-unconstrained one, which is exactly what made
    # the previous incident's boot log look clean when it wasn't.
    aw_length_uom = fields.Selection([
        ('ftin', 'Feet + Inches'),
        ('in', 'Inches'),
        ('mm', 'Millimetres'),
    ], string='Fenestration Length Unit', default='ftin',
        config_parameter='aw_fenestration.length_uom',
        help="How lengths are entered and displayed throughout Fenestration "
             "Design. Millimetres remain the stored source of truth "
             "regardless of this setting -- changing it only changes what "
             "you type into and see on screen.")

    # Also ir.config_parameter, for the same reason as above.
    aw_min_margin_pct = fields.Float(
        string='Minimum Margin %', default=20.0,
        config_parameter='aw_fenestration.min_margin_pct',
        help="A position priced below this is an error on its Checks and "
             "blocks quote confirmation. Placeholder value -- confirm it "
             "with the business before relying on it.")
