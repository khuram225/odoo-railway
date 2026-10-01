from odoo import fields, models

PARAM_STRIP = "pp_print_core.colour_strip_in"
PARAM_GAP = "pp_print_core.gap_in"


class ResConfigSettings(models.TransientModel):
    """Print settings live in ir.config_parameter: no new columns on shared core tables."""
    _inherit = "res.config.settings"

    print_colour_strip_in = fields.Float("Colour strip depth (in)", digits=(6, 3), default=0.2,
                                         config_parameter=PARAM_STRIP,
                                         help="Depth of the colour bar printed on each sheet; reduces the usable height.")
    print_gap_in = fields.Float("Gap between groups (in)", digits=(6, 3), default=0.0,
                                config_parameter=PARAM_GAP,
                                help="Space between column / row groups on the sheet (trim or bleed).")


def print_param(env, key, default):
    """Read a float print setting from ir.config_parameter."""
    value = env["ir.config_parameter"].sudo().get_param(key)
    try:
        return float(value) if value not in (None, False, "") else default
    except ValueError:
        return default
