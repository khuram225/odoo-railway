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

    # Glass suggestion (Lake City schedule). ir.config_parameter, like
    # the rest, so no column lands on res.company or res.users.
    # [revisit: read off Lake City, the client is to confirm both.]
    aw_glass_threshold_1_m2 = fields.Float(
        string='Larger glass from (m2)', default=4.5,
        config_parameter='aw_fenestration.glass_threshold_1_m2',
        help="A pane at or above this area is suggested 6+10+8 Clear "
             "Tempered.")
    aw_glass_threshold_2_m2 = fields.Float(
        string='Heaviest glass from (m2)', default=7.0,
        config_parameter='aw_fenestration.glass_threshold_2_m2',
        help="A pane at or above this area is suggested 8+8+8 Clear "
             "Tempered. Checked before the smaller threshold.")

    aw_glass_wet_words = fields.Char(
        string='Wet-room words',
        default='BATH, POWDER, TOILET, WC, WASHROOM',
        config_parameter='aw_fenestration.glass_wet_words',
        help="Comma separated. A window whose Location has a word that "
             "STARTS WITH one of these (any case) is suggested frosted "
             "glass: BATH matches Bath, Bathroom and GF-BATH.")

    # Cutting plan (spec 8, Phase 6c). ir.config_parameter again.
    aw_stock_lengths_ft = fields.Char(
        string='Stock Bar Lengths (ft)', default='14,16,18',
        config_parameter='aw_fenestration.stock_lengths_ft',
        help="Comma separated, e.g. '14,16,18'. The cutting plan costs "
             "every one of these and picks the cheapest.")
    aw_kerf_mm = fields.Float(
        string='Saw Kerf (mm)', default=5.0,
        config_parameter='aw_fenestration.kerf_mm',
        help="Reserved for every cut, including the last on a bar. "
             "Over-reserving slightly is the safe direction: a plan "
             "that buys one bar too few stops the saw.")
    aw_start_trim_mm = fields.Float(
        string='Bar Start Trim (mm)', default=0.0,
        config_parameter='aw_fenestration.start_trim_mm',
        help="Taken off every bar before anything is cut, for squaring "
             "the end. Defaults to 0 because nobody has measured it "
             "here — an invented figure would shorten every bar in the "
             "shop silently.")
    aw_safety_margin_mm = fields.Float(
        string='Bar Safety Margin (mm)', default=25.0,
        config_parameter='aw_fenestration.safety_margin_mm',
        help="Held back on every bar so a plan that is arithmetically "
             "exact still cuts in practice.")
    aw_solve_budget_s = fields.Float(
        string='Cutting Solver Budget (s)', default=20.0,
        config_parameter='aw_fenestration.solve_budget_s',
        help="Per profile group. When it runs out the best plan found "
             "so far is kept and reported as 'within N ft of optimal' "
             "rather than proven.")
    aw_offcut_min_mm = fields.Float(
        string='Minimum Reusable Offcut (mm)', default=400.0,
        config_parameter='aw_fenestration.offcut_min_mm',
        help="A bar's remainder at least this long is listed as "
             "'return to stock' rather than scrap.")
