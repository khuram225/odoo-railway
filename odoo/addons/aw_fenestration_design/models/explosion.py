# -*- coding: utf-8 -*-
"""The explosion engine (spec 6.5) and the checks (6.6).

Kept in its own file rather than bolted onto design.py: it is the one
place where every other table finally meets, and it is the part whose
output ends up on a real quote. A reader chasing "where does this cut
length come from" should land here.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.aw_fenestration_core.models.formula import (
    evaluate_formula, formula_truthy,
)

# Longest bar the shop stocks (spec 6.6). A piece longer than this can't
# be cut from one length and needs a coupler.
MAX_STOCK_BAR_MM = 18 * 304.8  # 18 ft

# How to say "the layout needs this" in the checks, per scope. Phrased
# as what the reader can see on the drawing, not as the internal scope
# name: "1 interlock junction" is actionable, "junction_interlock" is
# not.
# Keys the checks read that are NOT fields on aw.design.bom.line. Kept
# as one list because each is stripped in exactly one place, and a new
# one forgotten there fails the create with an obscure error.
CHECK_ONLY_KEYS = frozenset({
    'missing_product', 'position_id', 'missing_glass',
    'glass_without_product', 'glass_spec_name',
})

SCOPE_DEMAND_LABEL = {
    'frame': ('frame', 'frames'),
    'panel_opening': ('opening panel', 'opening panels'),
    'panel_fixed': ('fixed panel', 'fixed panels'),
    'panel_mesh': ('mesh panel', 'mesh panels'),
    'mesh_attachment': ('attached mesh', 'attached meshes'),
    'junction_mullion': ('mullion junction', 'mullion junctions'),
    'junction_meeting': ('meeting junction', 'meeting junctions'),
    'junction_interlock': ('interlock junction', 'interlock junctions'),
    'transom': ('transom', 'transoms'),
}


class AwDesign(models.Model):
    _inherit = 'aw.design'

    check_line_ids = fields.One2many(
        'aw.design.check', 'design_id', string='Checks', readonly=True)
    check_error_count = fields.Integer(compute='_compute_check_counts')
    check_warning_count = fields.Integer(compute='_compute_check_counts')

    @api.depends('check_line_ids.level')
    def _compute_check_counts(self):
        for design in self:
            levels = design.check_line_ids.mapped('level')
            design.check_error_count = levels.count('error')
            design.check_warning_count = levels.count('warning')

    # ------------------------------------------------------------------
    # context building
    # ------------------------------------------------------------------
    def _formula_context(self, panel_w=0.0, panel_h=0.0,
                         container_w=0.0, container_h=0.0,
                         panels_in_row=1, tracks=1):
        """The variables a formula may use (spec 6.1). One builder, so a
        formula means the same thing wherever it is evaluated."""
        self.ensure_one()
        return {
            'W': self.width_mm or 0.0,
            'H': self.height_mm or 0.0,
            'PW': panel_w,
            'PH': panel_h,
            'CW': container_w or (self.width_mm or 0.0),
            'CH': container_h or (self.height_mm or 0.0),
            'N': panels_in_row,
            'T': tracks,
        }

    # ------------------------------------------------------------------
    # profile pieces
    # ------------------------------------------------------------------
    def _section_lines_by_scope(self):
        """Active section lines grouped by their position's scope.

        Several lines may sit on one position; the lowest sequence is the
        active one and the rest are alternates, which is the rule that
        already governed Profile Sections before the engine existed.
        """
        self.ensure_one()
        chosen = {}
        section = self.profile_section_id
        for line in section.line_ids.sorted(lambda l: (l.sequence, l.id)):
            position = line.position_id
            if not position or not position.scope:
                continue
            if position.id in chosen:
                continue          # an alternate; the first one wins
            chosen[position.id] = line
        by_scope = {}
        for line in chosen.values():
            by_scope.setdefault(line.position_id.scope, []).append(line)
        return by_scope

    def _profile_variant(self, line):
        """Spec addition B: template and thickness come from the section
        line, finish from the DESIGN, falling back to the line's own."""
        finish = self.finish_id or line.finish_id
        return self.env['aw.profile.section.line']._variant_for(
            line.product_tmpl_id, line.thickness_id, finish)

    def _profile_pieces(self, line, context, label, panel_no=0):
        """Turn one section line into cut pieces.

        Edge decides how many and of which formula: 'sides' is two of the
        height formula, 'all' is two of each, anything else is one.
        """
        position = line.position_id
        length_w = line.length_formula or position.default_length
        length_h = (line.length_formula_h or position.default_length_h
                    or length_w)
        angle = line.cut_angle or position.default_angle or '90'
        qty_formula = line.qty_formula or position.default_qty or '1'
        qty = int(round(evaluate_formula(qty_formula, context, default=1))) or 1

        edge = position.edge
        if edge == 'sides':
            spec = [(length_h, 2)]
        elif edge == 'all':
            spec = [(length_w, 2), (length_h, 2)]
        else:
            spec = [(length_w, 1)]

        product = self._profile_variant(line)
        pieces = []
        for formula, count in spec:
            length = evaluate_formula(formula, context, default=0.0)
            pieces.append({
                'kind': 'profile',
                'product_id': product.id,
                'length_mm': length,
                'cut_angle': angle,
                'qty': count * qty,
                'panel_no': panel_no,
                'label': '%s %s' % (label, position.name),
                'position_id': position.id,
                'missing_product': not product,
            })
        return pieces

    # ------------------------------------------------------------------
    # the walk
    # ------------------------------------------------------------------
    def _explode_rows(self, rows, by_scope, box_w, box_h, out, demand):
        """Recursive walk: rows, panels, junctions, then into containers.

        Mirrors the drawing's own recursion, so a nested split produces
        BOM the same way it produces geometry.

        `demand` counts how many times the layout calls for each scope,
        whether or not the section has a line to satisfy it. It is
        incremented at the exact point the scope is decided, so what the
        checks think is needed can never drift from what the engine
        actually looked for.
        """
        self.ensure_one()
        total_h = sum(r.height_mm or 0 for r in rows) or 1
        for row_index, row in enumerate(rows):
            row_h = (row.height_mm or 0) / total_h * box_h
            leaves = row.leaf_ids
            total_w = sum(l.width_mm or 0 for l in leaves) or 1
            panels_in_row = len(leaves)

            for leaf_index, leaf in enumerate(leaves):
                leaf_w = (leaf.width_mm or 0) / total_w * box_w
                context = self._formula_context(
                    panel_w=leaf_w, panel_h=row_h,
                    container_w=box_w, container_h=box_h,
                    panels_in_row=panels_in_row,
                    tracks=max(leaves.mapped('track_no') or [1]) or 1)

                if leaf.child_row_ids:
                    # A container is not a panel: no sash, no glass, just
                    # whatever divides it, handled one level down.
                    self._explode_rows(
                        leaf.child_row_ids, by_scope, leaf_w, row_h, out,
                        demand)
                else:
                    self._explode_panel(leaf, by_scope, context, out, demand)

                # The junction AFTER this panel, if there is a next one.
                if leaf_index < len(leaves) - 1:
                    self._explode_junction(
                        leaf, by_scope, context, out, demand)

            # A transom between this row and the next.
            if row_index < len(rows) - 1:
                context = self._formula_context(
                    container_w=box_w, container_h=box_h,
                    panels_in_row=panels_in_row)
                demand['transom'] = demand.get('transom', 0) + 1
                for line in by_scope.get('transom', []):
                    out.extend(self._profile_pieces(
                        line, context, _('transom')))

    def _explode_panel(self, leaf, by_scope, context, out, demand):
        """One panel: its frame profiles, glass or infill, mesh, grid."""
        self.ensure_one()
        label = 'P%s' % (leaf.panel_no or 0)
        leaf_type = leaf.leaf_type_id
        opening = bool(leaf_type.has_hinge_side or leaf_type.has_slide_dir)
        is_mesh_leaf = leaf_type.code == 'MESH'

        if is_mesh_leaf:
            scope = 'panel_mesh'
        elif opening:
            scope = 'panel_opening'
        else:
            scope = 'panel_fixed'
        demand[scope] = demand.get(scope, 0) + 1
        for line in by_scope.get(scope, []):
            out.extend(self._profile_pieces(
                line, context, label, leaf.panel_no))

        # Attached mesh brings its own surround plus its own lines.
        if leaf.mesh_type_id:
            demand['mesh_attachment'] = demand.get('mesh_attachment', 0) + 1
            for line in by_scope.get('mesh_attachment', []):
                out.extend(self._profile_pieces(
                    line, context, '%s mesh' % label, leaf.panel_no))
            out.extend(self._attachment_lines(
                leaf.mesh_type_id.line_ids, context, 'mesh',
                '%s mesh' % label, leaf.panel_no))
            series = self.window_series_id
            out.append({
                'kind': 'mesh',
                'product_id': False,
                'panel_no': leaf.panel_no,
                'label': '%s %s' % (label, leaf.mesh_type_id.name),
                'glass_w': evaluate_formula(series.mesh_w, context),
                'glass_h': evaluate_formula(series.mesh_h, context),
                'qty': 1,
            })

        infill = leaf.infill_type_id
        uses_glass = infill.uses_glass if infill else True
        if infill and infill.kind != 'glass':
            out.extend(self._attachment_lines(
                infill.line_ids, context, 'infill',
                '%s %s' % (label, infill.name), leaf.panel_no))

        if uses_glass:
            series = self.window_series_id
            spec = leaf.glass_spec_id or self.glass_spec_id
            width = evaluate_formula(
                series.glass_sash_w if opening else series.glass_fixed_w,
                context)
            height = evaluate_formula(
                series.glass_sash_h if opening else series.glass_fixed_h,
                context)
            out.append({
                'kind': 'glass',
                'product_id': spec.product_id.id if spec else False,
                'glass_spec_id': spec.id if spec else False,
                'panel_no': leaf.panel_no,
                'label': '%s glass' % label,
                'glass_w': width,
                'glass_h': height,
                'qty': 1,
                # Not `missing_product`: that reports per line, and glass
                # is chosen once in the header, so a 6-panel design would
                # say the same thing six times. Flagged separately and
                # summarised once per design instead.
                'missing_glass': not spec,
                'glass_without_product': bool(spec and not spec.product_id),
                'glass_spec_name': spec.display_name if spec else '',
            })

        if leaf.grid_pattern_id:
            out.extend(self._attachment_lines(
                leaf.grid_pattern_id.line_ids, context, 'grid',
                '%s grid' % label, leaf.panel_no))

        # Hardware scoped per panel, filtered by leaf type as before.
        for line in self.hardware_set_id.line_ids:
            if line.scope != 'panel':
                continue
            if line.leaf_type_id and line.leaf_type_id != leaf_type:
                continue
            out.extend(self._hardware_line(
                line, context, label, leaf.panel_no))

    def _explode_junction(self, leaf, by_scope, context, out, demand):
        self.ensure_one()
        junction = leaf.junction_after or 'mullion'
        scope = 'junction_%s' % junction
        label = _('junction after P%s') % (leaf.panel_no or 0)
        demand[scope] = demand.get(scope, 0) + 1
        for line in by_scope.get(scope, []):
            out.extend(self._profile_pieces(line, context, label))
        for line in self.hardware_set_id.line_ids:
            if line.scope == 'junction':
                out.extend(self._hardware_line(line, context, label))

    def _hardware_line(self, line, context, label, panel_no=0):
        if not formula_truthy(line.condition_formula, context):
            return []
        qty = evaluate_formula(
            line.qty_formula or str(line.qty or 1), context, default=1)
        qty = int(round(qty))
        if qty <= 0:
            return []
        return [{
            'kind': 'hardware',
            'product_id': line.product_id.id,
            'qty': qty,
            'panel_no': panel_no,
            'label': '%s %s' % (label, line.product_id.display_name or ''),
            'missing_product': not line.product_id,
        }]

    def _attachment_lines(self, lines, context, kind, label, panel_no=0):
        out = []
        for line in lines:
            if not formula_truthy(line.condition_formula, context):
                continue
            qty = int(round(evaluate_formula(
                line.qty_formula, context, default=1)))
            if qty <= 0:
                continue
            out.append({
                'kind': kind,
                'product_id': line.product_id.id,
                'qty': qty,
                'panel_no': panel_no,
                'label': label,
                'missing_product': not line.product_id,
            })
        return out

    # ------------------------------------------------------------------
    # entry points
    # ------------------------------------------------------------------
    def action_explode(self):
        """Regenerate the BOM. Kept as a button for a manual re-run; it
        also happens on every save (see save_layout)."""
        for design in self:
            design._explode()
        return True

    def _explode(self):
        self.ensure_one()
        self.bom_line_ids.unlink()
        if not (self.width_mm > 0 and self.height_mm > 0):
            self._run_checks()
            return

        by_scope = self._section_lines_by_scope()
        out = []
        demand = {'frame': 1}

        frame_context = self._formula_context()
        for line in by_scope.get('frame', []):
            out.extend(self._profile_pieces(line, frame_context, _('frame')))

        self._explode_rows(
            self.row_ids, by_scope, self.width_mm, self.height_mm, out,
            demand)

        for line in self.hardware_set_id.line_ids:
            if line.scope == 'design':
                out.extend(self._hardware_line(
                    line, frame_context, _('design')))

        # Everything is per ONE window; the position may be for several.
        multiplier = max(1, self.qty or 1)
        sequence = 0
        for values in out:
            sequence += 10
            values = {k: v for k, v in values.items()
                      if k not in CHECK_ONLY_KEYS}
            values.update({
                'design_id': self.id,
                'sequence': sequence,
                'qty': (values.get('qty') or 1) * multiplier,
            })
            self.env['aw.design.bom.line'].create(values)

        self._run_checks(exploded=out, demand=demand)

    def _run_checks(self, exploded=None, demand=None):
        """Spec 6.6. Warnings are things to look at; errors are things
        that cannot be made as drawn."""
        self.ensure_one()
        self.check_line_ids.unlink()
        problems = []

        if not (self.width_mm > 0 and self.height_mm > 0):
            problems.append(('error', _("Width and height must be set.")))

        series = self.window_series_id
        allowed = set(series.leaf_type_ids.ids)
        for leaf in self._all_panels():
            label = _("Panel %s") % (leaf.panel_no or 0)
            if leaf.leaf_type_id and leaf.leaf_type_id.id not in allowed:
                problems.append(('error', _(
                    "%(panel)s is a %(type)s, which %(series)s doesn't allow.",
                    panel=label, type=leaf.leaf_type_id.display_name,
                    series=series.display_name)))

        # Positions that can never contribute, so the absence of a
        # profile from the cut list has a stated reason.
        for position in self.env['aw.profile.position'].search([]):
            if not position.scope:
                problems.append(('warning', _(
                    "Profile position '%s' has no scope, so the BOM "
                    "ignores it.", position.name)))

        problems.extend(self._missing_section_line_problems(demand or {}))

        for values in (exploded or []):
            if values.get('missing_product'):
                problems.append(('warning', _(
                    "No product for '%s'.", values.get('label') or '')))

        # Glass is chosen once, so it is reported once -- naming the two
        # places it can be set, since "no product for P1 glass" told the
        # reader what was wrong but not where to fix it.
        if any(v.get('missing_glass') for v in (exploded or [])):
            problems.append(('warning', _(
                "No glass selected for %s — choose Glass in the header, "
                "or set a glass override on the panel.",
                self.display_name)))
        without_product = {
            v.get('glass_spec_name') for v in (exploded or [])
            if v.get('glass_without_product')}
        for name in sorted(n for n in without_product if n):
            problems.append(('warning', _(
                "Glass '%s' has no product, so it can't be costed.", name)))

        for line in self.bom_line_ids:
            if line.kind == 'profile' and line.length_mm > MAX_STOCK_BAR_MM:
                problems.append(('error', _(
                    "'%(label)s' is %(len)s mm, longer than the longest "
                    "stock bar (%(max)s mm). It needs a coupler.",
                    label=line.label or '', len=round(line.length_mm),
                    max=round(MAX_STOCK_BAR_MM))))

        for level, message in problems:
            self.env['aw.design.check'].create({
                'design_id': self.id, 'level': level, 'message': message,
            })

    def _missing_section_line_problems(self, demand):
        """Required positions the layout needs and the section lacks.

        The silent case this exists for: a sliding design has an
        interlock junction, the Profile Section has no Interlock line,
        and the interlock simply never appears in the cut list. Nothing
        else notices -- the missing-product check only fires on a line
        that exists, so a position nobody configured produced no line to
        complain about.

        Only required positions warn. An optional one (Palay Bead on a
        sash profile with the channel built in) is absent on purpose.
        """
        self.ensure_one()
        section = self.profile_section_id
        if not section:
            # One error beats one warning per position: the section is
            # the thing to fix, and the rest would all say the same.
            return [('error', _(
                "No Profile Section is set, so this design has no "
                "profiles in its BOM at all."))]

        configured = set(section.line_ids.mapped('position_id').ids)
        needed = [scope for scope, count in demand.items() if count]
        positions = self.env['aw.profile.position'].search([
            ('is_required', '=', True),
            ('scope', 'in', needed),
        ])

        problems = []
        for position in positions:
            if position.id in configured:
                continue
            count = demand.get(position.scope, 0)
            singular, plural = SCOPE_DEMAND_LABEL.get(
                position.scope, (position.scope, position.scope))
            problems.append(('warning', _(
                "'%(section)s' has no '%(position)s' line "
                "(%(count)s %(what)s in this design).",
                section=section.display_name, position=position.name,
                count=count, what=singular if count == 1 else plural)))
        return problems

    def _all_panels(self):
        """Every real panel, containers skipped."""
        self.ensure_one()
        found = self.env['aw.design.leaf']

        def walk(rows):
            nonlocal found
            for row in rows:
                for leaf in row.leaf_ids:
                    if leaf.child_row_ids:
                        walk(leaf.child_row_ids)
                    else:
                        found |= leaf

        walk(self.row_ids)
        return found


class AwDesignCheck(models.Model):
    """One reported problem, so the configurator and the form show the
    same list rather than each deciding what counts."""
    _name = 'aw.design.check'
    _description = 'Fenestration Design Check'
    _order = 'level desc, id'

    design_id = fields.Many2one(
        'aw.design', required=True, ondelete='cascade', index=True)
    level = fields.Selection([
        ('error', 'Error'),
        ('warning', 'Warning'),
    ], required=True, default='warning')
    message = fields.Char(required=True)
