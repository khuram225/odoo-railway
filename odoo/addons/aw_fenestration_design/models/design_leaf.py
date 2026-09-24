# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AwDesignLeaf(models.Model):
    """Direct port of the prototype's row.leaves[] entries. leaf_type is
    now a Many2one to aw.leaf.type (aw_fenestration_core) instead of a
    hardcoded Selection — single source of truth, same table Window
    Series and Hardware Set lines both reference. Adding a new leaf
    mechanism no longer touches this file at all.

    Legality (which leaf types a given row's design.window_series_id
    actually allows, via window_series_id.leaf_type_ids) is still NOT
    enforced at this layer — that's the checks/validation step, not
    part of this bare data model.
    """
    _name = 'aw.design.leaf'
    _description = 'Fenestration Design Leaf'
    _order = 'sequence, id'

    row_id = fields.Many2one('aw.design.row', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    panel_no = fields.Integer(
        string='Panel',
        help="Position of this panel in the design, numbered 1..n in "
             "reading order. Stored rather than computed on the fly so the "
             "BOM, cut list and shop drawing can all cite the same "
             "reference, e.g. D1-P2. Assigned by "
             "aw.design._renumber_panels().")
    length_uom = fields.Selection(related='row_id.length_uom', string='Length Unit')

    # Not required, same reason as aw.design.width_mm: a new leaf entered
    # in the ft/in pair would trip the NOT NULL constraint at INSERT,
    # before the inverse that fills this in gets to run.
    width_mm = fields.Float(string='Width (mm)', default=0.0)
    width_ft = fields.Integer(string='Width (ft)',
        compute='_compute_width_ftin', inverse='_inverse_width_ftin')
    width_in = fields.Float(string='Width (in)',
        compute='_compute_width_ftin', inverse='_inverse_width_ftin',
        help="Decimals allowed, e.g. 6.5.")
    width_inch_total = fields.Float(string='Width (in)',
        compute='_compute_width_inch_total', inverse='_inverse_width_inch_total')

    is_auto = fields.Boolean(
        string='Automatic',
        help="Same mechanism as aw.design.row.is_auto, one level down: "
             "exactly one leaf per row should absorb the remainder so "
             "the row's leaf widths always sum to the design's overall "
             "Width. Not enforced at this layer yet.")

    # Subdivision. A leaf with child rows is a CONTAINER: it is not a panel
    # itself, it just holds the rows that divide its area. Containers carry
    # no leaf type, no direction and no panel number.
    child_row_ids = fields.One2many(
        'aw.design.row', 'parent_leaf_id', string='Sub-rows')
    is_container = fields.Boolean(
        compute='_compute_is_container', store=True,
        help="True when this leaf is subdivided, i.e. holds rows rather "
             "than being a panel in its own right.")

    # NOT required: a container has no leaf type. Enforced instead over
    # the finished tree by aw.design._check_panels_typed(), NOT by a
    # constraint here -- a container leaf is created before its sub-rows
    # exist (they need its id), so at create time it is indistinguishable
    # from a typeless panel and a per-record constraint rejected every
    # horizontal split.
    leaf_type_id = fields.Many2one(
        'aw.leaf.type', ondelete='restrict')
    # convenience related fields so the view can decide which direction
    # fields to show without re-deriving the leaf-type -> field-visibility
    # rule in XML — single source of truth stays on aw.leaf.type itself
    leaf_has_hinge_side = fields.Boolean(related='leaf_type_id.has_hinge_side', readonly=True)
    leaf_has_slide_dir = fields.Boolean(related='leaf_type_id.has_slide_dir', readonly=True)

    hinge_side = fields.Selection([
        ('left', 'Left'), ('right', 'Right'),
        ('top', 'Top'), ('bottom', 'Bottom'),
    ], help="Shown only for leaf types with has_hinge_side set.")
    swing = fields.Selection([
        ('in', 'In'), ('out', 'Out'),
    ], help="Shown only for leaf types with has_hinge_side set.")
    slide_dir = fields.Selection([
        ('left', 'Left'), ('right', 'Right'),
    ], help="Shown only for leaf types with has_slide_dir set.")

    track_no = fields.Integer(
        string='Track',
        help="Which track a sliding panel runs on, counting 1 from the "
             "innermost outwards. 0 on anything that doesn't slide.")

    junction_after = fields.Selection([
        ('mullion', 'Mullion'),
        ('meeting', 'Meeting'),
        ('interlock', 'Interlock'),
    ], help="What the boundary between this panel and the next one in "
            "the same row is made of. Empty on the last panel of a row, "
            "which has no next panel. Horizontal boundaries between rows "
            "are always transoms and aren't stored here.")

    @api.model
    def _default_junction(self, left, right):
        """What two neighbouring panels meet with, by default.

        Takes plain dicts rather than records so the same rule can run on
        a save payload and on stored leaves. Overridable per junction in
        the configurator afterwards -- this only decides the starting
        value.
        """
        if not right:
            return False          # last panel in the row: no junction
        codes = (left.get('leaf_type_code'), right.get('leaf_type_code'))
        if codes == ('SLIDER', 'SLIDER'):
            return 'interlock'
        # Two opening sashes hinged AWAY from the boundary meet each other
        # directly -- a French pair. Hinged towards it, or anything with a
        # fixed panel involved, needs a mullion between them.
        hinged = {'CASEMENT', 'TILTTURN'}
        if (codes[0] in hinged and codes[1] in hinged
                and left.get('hinge_side') == 'left'
                and right.get('hinge_side') == 'right'):
            return 'meeting'
        return 'mullion'

    @api.depends('child_row_ids')
    def _compute_is_container(self):
        for rec in self:
            rec.is_container = bool(rec.child_row_ids)

    @api.depends('width_mm')
    def _compute_width_ftin(self):
        for rec in self:
            total_in = rec.width_mm / 25.4
            ft = int(total_in // 12)
            rec.width_ft = ft
            rec.width_in = total_in - ft * 12

    def _inverse_width_ftin(self):
        for rec in self:
            rec.width_mm = rec.width_ft * 304.8 + rec.width_in * 25.4

    @api.depends('width_mm')
    def _compute_width_inch_total(self):
        for rec in self:
            rec.width_inch_total = rec.width_mm / 25.4

    def _inverse_width_inch_total(self):
        for rec in self:
            rec.width_mm = rec.width_inch_total * 25.4
