# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AwHardwareSet(models.Model):
    """A named hardware bundle for a Window Type, e.g. Logikal's
    'SIMPLYSMART symmetrical 7A': a package that expands into individually
    overridable lines (roller, lock, handle, hinge, stay...). Gaskets live
    here too, per the decision to fold them into hardware rather than glass.
    """
    _name = 'aw.hardware.set'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fenestration Hardware Set'
    _order = 'window_type_id, name'

    name = fields.Char(required=True, tracking=True)
    window_type_id = fields.Many2one(
        'aw.window.series', required=True, ondelete='restrict', index=True,
        tracking=True)
    active = fields.Boolean(default=True)
    notes = fields.Text()

    line_ids = fields.One2many(
        'aw.hardware.set.line', 'set_id', string='Hardware Lines')

    _sql_constraints = [
        ('name_type_uniq', 'unique(name, window_type_id)',
         'A hardware set name must be unique per Window Type.'),
    ]


class AwHardwareSetLine(models.Model):
    _name = 'aw.hardware.set.line'
    _description = 'Fenestration Hardware Set Line'
    _order = 'sequence, id'

    set_id = fields.Many2one(
        'aw.hardware.set', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='restrict',
        domain=lambda self: [(
            'categ_id', 'child_of',
            self.env.ref('aw_fenestration_core.product_category_hardware').id,
        )])
    qty = fields.Float(default=1.0, required=True)
    # -- 6.3 --------------------------------------------------------------
    # qty is kept and still shown, but qty_formula is what the engine
    # reads. The plain number migrates into it once, so an existing
    # Hardware Set keeps working without anyone retyping it.
    qty_formula = fields.Char(
        string='Quantity Formula',
        help="Result is a count. Variables: W H PW PH CW CH N T. "
             "Empty falls back to the plain Quantity.")
    condition_formula = fields.Char(
        string='Condition',
        help="The line is only generated when this is true. Empty means "
             "always.")
    scope = fields.Selection([
        ('design', 'Once per design'),
        ('panel', 'Per panel'),
        ('junction', 'Per junction'),
    ], default='panel', required=True)

    leaf_type_id = fields.Many2one('aw.leaf.type',
        help="Which leaf type in the design triggers this line. Blank "
             "means every leaf, e.g. a handle.")
    is_optional = fields.Boolean(
        default=True,
        help="Hardware lines default to optional — a sales user can drop "
             "or swap any line, per the choose/drop mechanism agreed for "
             "this module. Uncheck for a line that must never be removed.")

    @api.model
    def _seed_qty_formulas(self):
        """Move the plain qty into qty_formula, once.

        Fill-only-if-empty, so an upgrade never overwrites a formula
        someone wrote, and existing Hardware Sets keep the quantities
        they already had.
        """
        for line in self.with_context(active_test=False).search(
                [('qty_formula', 'in', (False, ''))]):
            line.qty_formula = str(line.qty or 1)
