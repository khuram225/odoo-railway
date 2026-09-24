# -*- coding: utf-8 -*-
"""Mesh, infill and grid types — what can be attached to a panel.

All three follow the same shape: a type record plus a line table of
product + qty formula + condition formula. Spec 5.1 says "same line
model as hardware", but aw.hardware.set.line has a plain `qty` Float and
no formula fields at all — those arrive in Phase 4 (6.1). So each type
gets its own line model carrying the formula columns now, unevaluated,
ready for the engine rather than waiting on it.
"""
from odoo import api, fields, models


class AwTypeLineMixin(models.AbstractModel):
    """Shared columns for the three line tables.

    Formulas are stored as text and NOT evaluated yet: the language and
    its variables are defined in spec 6.1, and inventing a dialect now
    would mean migrating every line when the real one lands.
    """
    _name = 'aw.type.line.mixin'
    _description = 'Fenestration Type Line (shared columns)'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        ondelete='restrict')
    qty_formula = fields.Char(
        string='Quantity Formula', default='1',
        help="Evaluated by the explosion engine in Phase 4. Variables are "
             "in mm, e.g. 'W', 'H', 'PANEL_W'. Plain numbers work today.")
    condition_formula = fields.Char(
        string='Condition',
        help="Optional. The line is only generated when this evaluates "
             "true. Empty means always.")
    notes = fields.Text()


class AwMeshType(models.Model):
    """A mesh ATTACHED to a panel (spec 5.1).

    Distinct from the Mesh leaf type, which is a sliding panel of its own
    on a mesh track and stays exactly as it is for sliding systems. This
    is the mesh fitted onto an openable or fixed panel.
    """
    _name = 'aw.mesh.type'
    _description = 'Fenestration Mesh Type'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    family_id = fields.Many2one(
        'aw.layout.family', string='Family',
        domain=[('kind', '=', 'mesh')],
        help="Which library family this mesh appears under.")
    mechanism = fields.Selection([
        ('fixed', 'Fixed'),
        ('hinged', 'Hinged'),
        ('pleated', 'Pleated'),
        ('roller', 'Roller'),
    ], required=True, default='fixed')
    pull = fields.Selection([
        ('left', 'Left'),
        ('right', 'Right'),
        ('center', 'Centre'),
        ('sides', 'Sides'),
        ('vertical', 'Vertical'),
    ], help="Which way a pleated or roller mesh draws. Empty for fixed "
            "and hinged meshes.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'aw.mesh.type.line', 'mesh_type_id', string='Lines')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Mesh Type code must be unique.'),
    ]


class AwMeshTypeLine(models.Model):
    _name = 'aw.mesh.type.line'
    _inherit = ['aw.type.line.mixin']
    _description = 'Fenestration Mesh Type Line'

    mesh_type_id = fields.Many2one(
        'aw.mesh.type', required=True, ondelete='cascade', index=True)


class AwInfillType(models.Model):
    """What fills a panel: glass, a solid panel, a louvre, a fan, an AC
    cutout (spec 5.2).

    uses_glass is what the configurator keys off: a panel whose infill
    doesn't use glass has no glass to override, so that field is hidden
    rather than left to be set meaninglessly.
    """
    _name = 'aw.infill.type'
    _description = 'Fenestration Infill Type'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    kind = fields.Selection([
        ('glass', 'Glass'),
        ('panel', 'Solid panel'),
        ('louvre', 'Louvre'),
        ('fan', 'Exhaust fan'),
        ('ac', 'AC cutout'),
    ], required=True, default='glass')
    uses_glass = fields.Boolean(
        default=False,
        help="Whether this infill is glazed. Only glazed panels offer a "
             "glass override.")
    adjustable = fields.Boolean(
        help="Louvre blades that can be angled, as opposed to fixed.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'aw.infill.type.line', 'infill_type_id', string='Lines')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Infill Type code must be unique.'),
    ]


class AwInfillTypeLine(models.Model):
    _name = 'aw.infill.type.line'
    _inherit = ['aw.type.line.mixin']
    _description = 'Fenestration Infill Type Line'

    infill_type_id = fields.Many2one(
        'aw.infill.type', required=True, ondelete='cascade', index=True)


class AwGridPattern(models.Model):
    """Georgian bars over a panel (spec 5.4).

    5.4 gives the pattern a single "bar product". That is a line here
    instead, like the other two: a real grid usually needs more than one
    product (horizontal and vertical bars, end caps), and one shape for
    all three type tables is easier to feed to the engine in Phase 4.
    """
    _name = 'aw.grid.pattern'
    _description = 'Fenestration Grid Pattern'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    kind = fields.Selection([
        ('rect', 'Rectangular (rows x columns)'),
        ('perimeter', 'Perimeter'),
    ], required=True, default='rect')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'aw.grid.pattern.line', 'grid_pattern_id', string='Lines')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Grid Pattern code must be unique.'),
    ]


class AwGridPatternLine(models.Model):
    _name = 'aw.grid.pattern.line'
    _inherit = ['aw.type.line.mixin']
    _description = 'Fenestration Grid Pattern Line'

    grid_pattern_id = fields.Many2one(
        'aw.grid.pattern', required=True, ondelete='cascade', index=True)
