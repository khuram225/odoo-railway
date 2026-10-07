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
    _description = 'Fenestration Fly Screen'
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
        ('rollup', 'Roll-up'),
        ('zigzag', 'Zig-zag'),
    ], required=True, default='fixed')
    opening_only = fields.Boolean(
        string='Opening sashes only', default=False,
        help="Offer this only on opening sashes (casement, awning, "
             "hopper, tilt & turn). A roll-up screen rolls back into a "
             "cassette on the sash, so it has no place on a fixed light "
             "or a slider.")
    pull = fields.Selection([
        ('left', 'Left'),
        ('right', 'Right'),
        ('center', 'Centre'),
        ('sides', 'Sides'),
        ('vertical', 'Vertical'),
    ], help="Which way a pleated or roller mesh draws. Empty for fixed "
            "and hinged meshes.")
    # Part 2 (revised). Empty means every system, which is the common
    # case and the safe default: a new option is offered everywhere
    # until somebody narrows it. A pleated fly screen belongs on an
    # openable system and not on a slider, and that is a fact about the
    # option rather than about any one design.
    available_series_ids = fields.Many2many(
        'aw.window.series', string='Available on',
        help="Offer this option only on these window systems. Leave "
             "empty to offer it on all of them.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'aw.mesh.type.line', 'mesh_type_id', string='Lines')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Fly screen code must be unique.'),
    ]

    # The retractable types merged into "Zig-zag mesh": the roll-up and
    # the four pleated ones. xmlids, not codes: a code can be edited.
    ZIGZAG_XMLID = 'aw_fenestration_design.mesh_type_zigzag'
    ZIGZAG_MERGED_XMLIDS = (
        'mesh_type_rollup', 'mesh_type_pleated_l', 'mesh_type_pleated_r',
        'mesh_type_pleated_dc', 'mesh_type_pleated_ds')
    ZIGZAG_PARAM = 'aw_fenestration.mesh_zigzag_merged'

    @api.model
    def _migrate_to_zigzag(self):
        """Move roll-up and pleated screens onto Zig-zag mesh, ONCE.

        Each panel keeps its side: a roll-up its cassette side (left if
        it somehow had none), a pleated single the side it pulls to, a
        pleated double (centre or sides) both. The old types are
        ARCHIVED, never deleted, so nothing that points at them breaks.

        Zig-zag is available on the union of the old types' systems --
        which is every system as soon as any one of them was offered
        everywhere, as the roll-up was.

        A drawing that was current stays current: the screen is drawn
        the same, so the layout fingerprint is re-taken after the move
        rather than leaving every affected window flagged "out of date".
        The bill of materials is not re-run, so no price moves; a BOM
        line keeps the old screen's name until the window is next saved.
        """
        param = self.env['ir.config_parameter'].sudo()
        if param.get_param(self.ZIGZAG_PARAM):
            return 0
        zigzag = self.env.ref(self.ZIGZAG_XMLID, raise_if_not_found=False)
        if not zigzag:
            return 0
        old = self.env['aw.mesh.type']
        for xmlid in self.ZIGZAG_MERGED_XMLIDS:
            old |= self.env.ref('aw_fenestration_design.%s' % xmlid,
                                raise_if_not_found=False) or old.browse()
        old = old.with_context(active_test=False)

        if old and all(t.available_series_ids for t in old):
            zigzag.available_series_ids = old.available_series_ids

        Leaf = self.env['aw.design.leaf']
        leaves = Leaf.search([('mesh_type_id', 'in', old.ids)])
        designs = leaves.mapped('row_id.design_id')
        was_current = designs.filtered('elevation_is_current')
        for leaf in leaves:
            mesh = leaf.mesh_type_id
            if mesh.mechanism == 'pleated':
                if mesh.pull in ('center', 'sides'):
                    side = 'both'
                else:
                    side = 'right' if mesh.pull == 'right' else 'left'
            else:
                side = leaf.mesh_cassette_side or 'left'
            leaf.write({'mesh_type_id': zigzag.id,
                        'mesh_cassette_side': side,
                        'mesh_hinge_side': False})
        # The fingerprint reads the new type and side, so take it after.
        for design in was_current:
            design.elevation_hash = design._layout_fingerprint()
        old.write({'active': False})
        param.set_param(self.ZIGZAG_PARAM, '1')
        return len(leaves)


class AwMeshTypeLine(models.Model):
    _name = 'aw.mesh.type.line'
    _inherit = ['aw.type.line.mixin']
    _description = 'Fenestration Fly Screen Line'

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
    family_id = fields.Many2one(
        'aw.layout.family', string='Family',
        domain=[('kind', '=', 'infill')],
        help="Which library family this infill appears under.")
    uses_glass = fields.Boolean(
        default=False,
        help="Whether this infill is glazed. Only glazed panels offer a "
             "glass override.")
    adjustable = fields.Boolean(
        help="Louvre blades that can be angled, as opposed to fixed.")
    # Part 2 (revised). Empty means every system, which is the common
    # case and the safe default: a new option is offered everywhere
    # until somebody narrows it. A pleated fly screen belongs on an
    # openable system and not on a slider, and that is a fact about the
    # option rather than about any one design.
    available_series_ids = fields.Many2many(
        'aw.window.series', string='Available on',
        help="Offer this option only on these window systems. Leave "
             "empty to offer it on all of them.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'aw.infill.type.line', 'infill_type_id', string='Lines')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Infill Type code must be unique.'),
    ]


    @api.model
    def _seed_default_family(self):
        """Point infill types at the Add-ons family, once.

        The types were seeded before they had a family field, and their
        data file is noupdate="1", so adding family_id there would only
        reach a fresh install. Fill-only-if-empty, like every other seed
        here, so a regrouping done in the UI survives.
        """
        family = self.env.ref(
            'aw_fenestration_design.layout_family_add',
            raise_if_not_found=False)
        if not family:
            return
        for infill in self.with_context(active_test=False).search(
                [('family_id', '=', False)]):
            infill.family_id = family.id


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
    # Part 2 (revised). Empty means every system, which is the common
    # case and the safe default: a new option is offered everywhere
    # until somebody narrows it. A pleated fly screen belongs on an
    # openable system and not on a slider, and that is a fact about the
    # option rather than about any one design.
    available_series_ids = fields.Many2many(
        'aw.window.series', string='Available on',
        help="Offer this option only on these window systems. Leave "
             "empty to offer it on all of them.")
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
