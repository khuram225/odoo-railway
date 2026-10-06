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
    evaluate_formula, formula_truthy, substitute_formula,
)

from .cut_algorithm import max_piece_mm

# Keys the checks read that are NOT fields on aw.design.bom.line. Kept
# as one list because each is stripped in exactly one place, and a new
# one forgotten there fails the create with an obscure error.
CHECK_ONLY_KEYS = frozenset({
    'missing_product', 'missing_product_reason', 'position_id',
    'missing_glass',
    'glass_without_product', 'glass_spec_name', '_order',
})

# How to say "the layout needs this" in the checks, per scope. Phrased
# as what the reader can see on the drawing, not as the internal scope
# name: "1 interlock junction" is actionable, "junction_interlock" is
# not.
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

    @api.model
    def _max_piece_mm(self):
        """The longest piece that can be cut from one bar.

        Longest stock length, less the start trim, the safety margin and
        one saw cut. Quoted at 45 degrees because a mitre loses more
        than a square cut, so the number shown is the one that always
        holds.
        """
        settings = self.env['aw.cut.plan']._settings()
        longest = max(settings['stock_ft']) * 304.8
        return max_piece_mm(
            longest, settings['start_trim'], settings['safety_margin'],
            settings['kerf'], '45')

    def _deduction_rules(self):
        """Where the glass and mesh deductions come from.

        The SPEC, since phase 7d: two specs of one system can use
        different beads and so different deductions. Falls back to the
        system for a design that has no spec yet -- the fields have the
        same names on both, and the migration copied the system's
        values onto every spec, so the answer is the same either way on
        an existing database.
        """
        self.ensure_one()
        return self.template_id or self.window_series_id

    def _deduction_source(self):
        """Where a glass or mesh deduction came from, in words.

        Named off the same fallback _deduction_rules() uses, so the
        calculation sheet cannot claim the spec supplied a rule that
        actually came from the system.
        """
        self.ensure_one()
        if self.template_id:
            return _('Spec: %s', self.template_id.display_name or '')
        return _('System: %s', self.window_series_id.display_name or '')

    # ------------------------------------------------------------------
    # context building
    # ------------------------------------------------------------------
    def _formula_context(self, panel_w=0.0, panel_h=0.0,
                         container_w=0.0, container_h=0.0,
                         panels_in_row=1, tracks=1, lock_side_mm=0.0):
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
            # Zero everywhere except a lock bar's own evaluation: no
            # other formula has a lock side, and a stale LS from a
            # previous panel would be worse than nothing.
            'LS': lock_side_mm,
        }

    # ------------------------------------------------------------------
    # profile pieces
    # ------------------------------------------------------------------
    def _section_lines_by_scope(self):
        """The spec's profile lines, grouped by their position's scope.

        One line per position since phase 7d -- the alternates live ON
        the line -- so this no longer has to pick a winner among
        duplicates. The constraint enforces that; the first-wins guard
        stays as a belt for the legacy section-owned rows, which may
        still be duplicated until they are dropped.
        """
        self.ensure_one()
        chosen = {}
        for line in self._spec_profile_lines().sorted(
                lambda l: (l.sequence, l.id)):
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

    def _overrides_by_key(self):
        """This window's changes, keyed by what each one replaces.

        Built once per explosion and passed nowhere: the walk asks for
        it per line, and a design has a handful of overrides at most.
        Profiles are keyed by POSITION and hardware by LINE -- see
        override.py for why those and not the products.
        """
        self.ensure_one()
        by_position, by_hardware = {}, {}
        for change in self.override_ids:
            if change.kind == 'profile' and change.position_id:
                by_position[change.position_id.id] = change
            elif change.kind == 'hardware' and change.hardware_line_id:
                by_hardware[change.hardware_line_id.id] = change
        return by_position, by_hardware

    def _profile_variant(self, line, product_tmpl=None):
        """Spec addition B: template and thickness come from the section
        line, finish from the DESIGN, falling back to the line's own.

        Phase 7c: a change recorded for this window replaces the
        line's template and thickness. The finish is deliberately NOT
        part of an override -- it is a property of the window, so a
        changed profile follows the window's colour like every other.

        Phase 7d: `product_tmpl` overrides the line's default, which is
        how a divider built from one of the line's ALTERNATES is
        resolved. The thickness and finish still come from the line and
        the design, so an alternate is costed by exactly the same path
        as the default -- an alternate resolved differently from a
        default is how two numbers for one profile appear.
        """
        change = self._overrides_by_key()[0].get(line.position_id.id)
        if change:
            return change._profile_variant_for(self)
        # Phase 7e: the DESIGN's finish, full stop. The line has none to
        # fall back to any more, which is the point -- one window, one
        # colour, decided where the window is.
        return self.env['aw.profile.section.line']._variant_for(
            product_tmpl or line.product_tmpl_id, line.thickness_id,
            self.finish_id)

    def _profile_change(self, line):
        """The change replacing this profile line, if any."""
        return self._overrides_by_key()[0].get(line.position_id.id)

    def _profile_variant_problem(self, line, product_tmpl=None):
        """Why _profile_variant found nothing, in words the reader can
        act on. Asked only when it found nothing."""
        return self.env['aw.profile.section.line']._variant_problem(
            product_tmpl or line.product_tmpl_id, line.thickness_id,
            self.finish_id)

    def _profile_pieces(self, line, context, label, panel_no=0,
                        product_tmpl=None):
        """Turn one section line into cut pieces.

        Edge decides how many and of which formula: 'sides' is two of the
        height formula, 'all' is two of each, anything else is one.

        `product_tmpl` builds the pieces from one of the line's
        alternates instead of its default -- the lengths, angles and
        quantities are the position's, which is the point: choosing a
        heavier mullion changes the profile, not the geometry.
        """
        position = line.position_id
        length_w = line.length_formula or position.default_length
        length_h = (line.length_formula_h or position.default_length_h
                    or length_w)
        # Where each rule came from, read off the SAME fallback chain
        # that chose it, so the sheet cannot name a source the length
        # did not actually come from.
        spec_name = line.spec_id.display_name or ''
        source_w = (_('Spec line: %s', spec_name) if line.length_formula
                    else _('Position default: %s', position.name or ''))
        if line.length_formula_h:
            source_h = _('Spec line: %s', spec_name)
        elif position.default_length_h:
            source_h = _('Position default: %s', position.name or '')
        else:
            source_h = source_w       # fell back to the width rule
        angle = line.cut_angle or position.default_angle or '90'
        qty_formula = line.qty_formula or position.default_qty or '1'
        qty = int(round(evaluate_formula(qty_formula, context, default=1))) or 1

        # Clockwise from the top, viewed from inside: top 1, right 2,
        # bottom 3, left 4 (spec B). Carried per piece so the reference
        # numbering does not have to re-derive which side is which.
        edge = position.edge
        if edge == 'sides':
            spec = [(length_h, 2, (2, 4), source_h)]
        elif edge == 'all':
            spec = [(length_w, 2, (1, 3), source_w),
                    (length_h, 2, (2, 4), source_h)]
        elif edge == 'bottom':
            spec = [(length_w, 1, (3,), source_w)]
        elif edge == 'top':
            spec = [(length_w, 1, (1,), source_w)]
        else:
            spec = [(length_w, 1, (0,), source_w)]

        product = self._profile_variant(line, product_tmpl=product_tmpl)
        change = self._profile_change(line)
        # Worked out once per section line rather than per piece: four
        # frame members share one line, and they would all give the
        # same answer.
        reason = ('' if product
                  else self._profile_variant_problem(
                      line, product_tmpl=product_tmpl))
        pieces = []
        # ONE DICT PER PHYSICAL PIECE, not one per formula. Four frame
        # members cannot share a BOM line and still carry four distinct
        # references (spec B), and the cut list wants them separate
        # anyway -- each one is a cut.
        for formula, count, edges, source in spec:
            length = evaluate_formula(formula, context, default=0.0)
            # Rendered from the same context the length was evaluated
            # with, so the working out and the result always agree.
            worked = substitute_formula(formula, context)
            for index in range(count * qty):
                pieces.append({
                    'kind': 'profile',
                    'product_id': product.id,
                    'length_mm': length,
                    'cut_angle': angle,
                    'qty': 1,
                    'panel_no': panel_no,
                    'label': '%s %s' % (label, position.name),
                    'position_id': position.id,
                    'missing_product': not product,
                    'missing_product_reason': reason,
                    'is_changed': bool(change),
                    'change_note': change.note if change else '',
                    'calc_rule': formula or '',
                    'calc_source': source,
                    'calc_worked': worked,
                    '_order': (
                        self._piece_rank(position.scope),
                        panel_no,
                        edges[index % len(edges)] if edges else 0,
                        position.sequence or 0,
                        index,
                    ),
                })
        return pieces

    def _piece_reference(self, unit, number, units_total):
        """'D1.3', or 'D1-2.3' when the position is for several units.

        Derived from the design and the piece's place in it, never from
        the cutting plan -- re-optimising must never renumber a piece
        somebody has already written on a bar.
        """
        self.ensure_one()
        base = self.name or '?'
        if units_total > 1:
            return '%s-%s.%s' % (base, unit, number)
        return '%s.%s' % (base, number)

    @staticmethod
    def _piece_rank(scope):
        """Frame first, then whatever divides the opening, then panels.

        The order the references are handed out in (spec B), so it has
        to be stable against anything the optimiser later does.
        """
        if scope == 'frame':
            return 0
        if scope in ('junction_mullion', 'junction_meeting',
                     'junction_interlock', 'transom'):
            return 1
        return 2

    # ------------------------------------------------------------------
    # the walk
    # ------------------------------------------------------------------
    def _explode_rows(self, rows, by_scope, box_w, box_h, out, demand,
                      spans):
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
                        demand, spans)
                else:
                    self._explode_panel(leaf, by_scope, context, out, demand)

                # The junction AFTER this panel, if there is a next one.
                if leaf_index < len(leaves) - 1:
                    # The divider spans the row's height, which is what
                    # a span rating is about.
                    self._explode_junction(
                        leaf, by_scope, context, out, demand, row_h, spans)

            # A transom between this row and the next.
            if row_index < len(rows) - 1:
                context = self._formula_context(
                    container_w=box_w, container_h=box_h,
                    panels_in_row=panels_in_row)
                demand['transom'] = demand.get('transom', 0) + 1
                for line, product in self._divider_lines(
                        'transom', by_scope, row.divider_product_id, box_w,
                        spans):
                    out.extend(self._profile_pieces(
                        line, context, _('transom'),
                        product_tmpl=product))

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
        lock_position = self._lock_bar_position()
        for line in by_scope.get(scope, []):
            # The lock bar is in this scope but is not one of the panel's
            # four sides: it sits on ONE edge, decided per panel, and
            # only when the panel is locked. Handled below so it is not
            # generated with LS = 0 on every opening panel.
            if lock_position and line.position_id == lock_position:
                continue
            out.extend(self._profile_pieces(
                line, context, label, leaf.panel_no))
        if scope == 'panel_opening':
            out.extend(self._lock_bar_pieces(leaf, by_scope, context, label))

        # Attached mesh brings its own surround plus its own lines.
        if leaf.mesh_type_id:
            demand['mesh_attachment'] = demand.get('mesh_attachment', 0) + 1
            for line in by_scope.get('mesh_attachment', []):
                out.extend(self._profile_pieces(
                    line, context, '%s mesh' % label, leaf.panel_no))
            out.extend(self._attachment_lines(
                leaf.mesh_type_id.line_ids, context, 'mesh',
                '%s mesh' % label, leaf.panel_no))
            rules = self._deduction_rules()
            out.append({
                'kind': 'mesh',
                'product_id': False,
                'panel_no': leaf.panel_no,
                'label': '%s %s' % (label, leaf.mesh_type_id.name),
                'glass_w': evaluate_formula(rules.mesh_w, context),
                'glass_h': evaluate_formula(rules.mesh_h, context),
                'calc_rule': rules.mesh_w or '',
                'calc_rule_h': rules.mesh_h or '',
                'calc_source': self._deduction_source(),
                'calc_worked': substitute_formula(rules.mesh_w, context),
                'calc_worked_h': substitute_formula(rules.mesh_h, context),
                'qty': 1,
            })

        infill = leaf.infill_type_id
        uses_glass = infill.uses_glass if infill else True
        if infill and infill.kind != 'glass':
            out.extend(self._attachment_lines(
                infill.line_ids, context, 'infill',
                '%s %s' % (label, infill.name), leaf.panel_no))

        if uses_glass:
            rules = self._deduction_rules()
            spec = leaf.glass_spec_id or self.glass_spec_id
            rule_w = rules.glass_sash_w if opening else rules.glass_fixed_w
            rule_h = rules.glass_sash_h if opening else rules.glass_fixed_h
            width = evaluate_formula(rule_w, context)
            height = evaluate_formula(rule_h, context)
            out.append({
                'kind': 'glass',
                'product_id': spec.product_id.id if spec else False,
                'glass_spec_id': spec.id if spec else False,
                'panel_no': leaf.panel_no,
                'label': '%s glass' % label,
                'glass_w': width,
                'glass_h': height,
                'calc_rule': rule_w or '',
                'calc_rule_h': rule_h or '',
                'calc_source': self._deduction_source(),
                'calc_worked': substitute_formula(rule_w, context),
                'calc_worked_h': substitute_formula(rule_h, context),
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
        for line in self._spec_hardware_lines():
            if line.scope != 'panel':
                continue
            if line.leaf_type_id and line.leaf_type_id != leaf_type:
                continue
            out.extend(self._hardware_line(
                line, context, label, leaf.panel_no))

    # ------------------------------------------------------------------
    # lock bar (phase 7d)
    # ------------------------------------------------------------------
    def _lock_bar_position(self):
        """The Lock Bar position, or nothing on a database without it."""
        return self.env.ref(
            'aw_fenestration_core.pos_lock_bar', raise_if_not_found=False)

    #: Every lock side is "the far edge from the way the sash moves",
    #: which is one mapping for both mechanisms rather than two.
    _OPPOSITE_EDGE = {
        'left': 'right', 'right': 'left',
        'top': 'bottom', 'bottom': 'top',
    }

    @classmethod
    def _lock_edge(cls, leaf):
        """Which edge of the sash the lock is on.

        HINGED: opposite the hinge. Hinge left -> the lock is on the
        right, and so on round; a top-hung sash locks at the bottom, a
        bottom-hung one at the top, and a tilt & turn locks opposite
        its side hinge.

        SLIDING: the edge the sash CLOSES TOWARDS, which is opposite
        its slide direction -- a sash that slides left to open shuts
        to the right, so the lock bar is on its right edge. Same
        mapping, because both are "the far edge from the way the sash
        moves". The PROFILE differs (the client's sliding systems use
        a different lock bar), but that comes from the sliding
        system's own spec, not from here: a system with no Lock Bar
        line simply produces no piece.

        [revisit] The client is to confirm the side and the profile
        code for Double Glaze - Sliding.
        """
        if leaf.hinge_side:
            return cls._OPPOSITE_EDGE.get(leaf.hinge_side, '')
        return cls._OPPOSITE_EDGE.get(leaf.slide_dir or '', '')

    def _lock_side_length(self, edge, by_scope, context):
        """LS: the sash profile length already generated for `edge`.

        The lock bar is specified as a fraction of the stile it is
        fitted to, so it has to be that piece's length rather than the
        panel's -- the stile is the panel less the section's own
        deduction, and 0.8 of the wrong one is several mm out on every
        sash. Taken from the same section line the panel's own sash
        piece comes from, so the two can never disagree.

        Falls back to the raw panel dimension when the section has no
        sash profile for that edge: 0.8 of the panel is a worse answer
        than 0.8 of the stile and a much better one than zero.
        """
        self.ensure_one()
        vertical = edge in ('left', 'right')
        wanted = 'sides' if vertical else edge
        for line in by_scope.get('panel_opening', []):
            position = line.position_id
            if position == self._lock_bar_position():
                continue
            if position.edge == wanted:
                return evaluate_formula(
                    line.length_formula or position.default_length,
                    context, default=0.0)
            if position.edge == 'all':
                # 'all' carries both formulas; the vertical pieces use
                # the height-edge one when it is set.
                formula = (
                    (line.length_formula_h or position.default_length_h
                     or line.length_formula or position.default_length)
                    if vertical
                    else (line.length_formula or position.default_length))
                return evaluate_formula(formula, context, default=0.0)
        return context.get('PH' if vertical else 'PW', 0.0)

    def _lock_bar_pieces(self, leaf, by_scope, context, label):
        """The lock bar for one opening panel, if it has one."""
        self.ensure_one()
        position = self._lock_bar_position()
        if not position or not leaf.has_lock:
            return []
        lines = [l for l in by_scope.get('panel_opening', [])
                 if l.position_id == position]
        if not lines:
            return []
        edge = self._lock_edge(leaf)
        if not edge:
            return []
        lock_context = dict(context)
        lock_context['LS'] = self._lock_side_length(edge, by_scope, context)
        pieces = []
        for line in lines:
            pieces.extend(self._profile_pieces(
                line, lock_context, label, leaf.panel_no))
        return pieces

    def _explode_junction(self, leaf, by_scope, context, out, demand,
                          span_mm=0.0, spans=None):
        self.ensure_one()
        junction = leaf.junction_after or 'mullion'
        scope = 'junction_%s' % junction
        label = _('junction after P%s') % (leaf.panel_no or 0)
        demand[scope] = demand.get(scope, 0) + 1
        for line, product in self._divider_lines(
                scope, by_scope, leaf.divider_product_id, span_mm, spans):
            out.extend(self._profile_pieces(
                line, context, label, product_tmpl=product))
        for line in self._spec_hardware_lines():
            if line.scope == 'junction':
                out.extend(self._hardware_line(line, context, label))

    def _divider_lines(self, scope, by_scope, chosen, span_mm, spans):
        """(line, profile) pairs to build this divider from.

        Phase 7d: `chosen` is a product TEMPLATE now, not a line. One
        line holds the position's default and its alternates, so the
        question a divider answers is "which of these profiles", which
        is what the estimator was choosing all along -- the old version
        stored a whole line and had to check it still belonged to this
        spec and this scope.

        A choice is honoured only when the line actually OFFERS it. An
        alternate removed from the spec afterwards falls back to the
        default rather than quietly cutting a profile the spec no longer
        lists, and empty has always meant the default.
        """
        self.ensure_one()
        lines = by_scope.get(scope, [])
        if not lines:
            return []
        line = lines[0]
        product = line.product_tmpl_id
        if chosen and chosen in line._profile_choices():
            product = chosen
        self._record_span(line, product, span_mm, spans)
        return [(line, product)]

    @staticmethod
    def _record_span(line, product, span_mm, spans):
        """Remember the longest span each PROFILE was asked to carry.

        Keyed on the product since phase 7d, because the rating moved
        onto the profile: one line can produce two different profiles in
        one design (a default on a narrow bay, an alternate on a wide
        one), and keying on the line would have reported whichever came
        last against both spans.

        `spans` is a plain dict threaded through the walk. It used to
        be set on the record, which looked convenient and is not
        possible: Odoo 19 records use __slots__, so `self._aw_spans = {}`
        raised AttributeError on the first save of any design. A record
        can hold fields and nothing else.
        """
        if spans is None or not (line and product) or not span_mm:
            return
        seen = spans.setdefault((line.id, product.id), [line, product, 0.0])
        seen[2] = max(seen[2], span_mm)

    def _hardware_line(self, line, context, label, panel_no=0):
        if not formula_truthy(line.condition_formula, context):
            return []
        change = self._overrides_by_key()[1].get(line.id)
        # A change may set the quantity as well as the product, and an
        # explicit 0 is a real instruction: it is how the Spec tab drops
        # a hardware line this one window does not need.
        if change:
            qty = change.qty
        else:
            qty = evaluate_formula(
                line.qty_formula or str(line.qty or 1), context, default=1)
        qty = int(round(qty))
        if qty <= 0:
            return []
        product = change.product_id if change else line.product_id
        return [{
            'kind': 'hardware',
            'product_id': product.id,
            'qty': qty,
            'panel_no': panel_no,
            'label': '%s %s' % (label, product.display_name or ''),
            'missing_product': not product,
            'is_changed': bool(change),
            'change_note': change.note if change else '',
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
        # Longest span asked of each divider option. Local to this
        # explosion and passed down the walk -- see _record_span.
        spans = {}

        frame_context = self._formula_context()
        for line in by_scope.get('frame', []):
            out.extend(self._profile_pieces(line, frame_context, _('frame')))

        self._explode_rows(
            self.row_ids, by_scope, self.width_mm, self.height_mm, out,
            demand, spans)

        for line in self._spec_hardware_lines():
            if line.scope == 'design':
                out.extend(self._hardware_line(
                    line, frame_context, _('design')))

        # Everything above is per ONE window; the position may be for
        # several. Profiles are expanded into one line per physical
        # piece per unit so each can carry its own reference; everything
        # else keeps an aggregate quantity, because nobody labels a
        # screw.
        multiplier = max(1, self.qty or 1)
        profiles = sorted(
            (v for v in out if v.get('kind') == 'profile'),
            key=lambda v: v.get('_order') or ())
        others = [v for v in out if v.get('kind') != 'profile']

        sequence = 0
        for unit in range(1, multiplier + 1):
            for index, values in enumerate(profiles, start=1):
                sequence += 10
                values = {k: v for k, v in values.items()
                          if k not in CHECK_ONLY_KEYS}
                values.update({
                    'design_id': self.id,
                    'sequence': sequence,
                    'qty': 1,
                    'unit_no': unit,
                    'piece_ref': self._piece_reference(unit, index,
                                                       multiplier),
                })
                self.env['aw.design.bom.line'].create(values)

        for values in others:
            sequence += 10
            values = {k: v for k, v in values.items()
                      if k not in CHECK_ONLY_KEYS}
            values.update({
                'design_id': self.id,
                'sequence': sequence,
                'qty': (values.get('qty') or 1) * multiplier,
            })
            self.env['aw.design.bom.line'].create(values)

        # Cost before the checks run, so the checks can report on it.
        self._cost_bom_lines()
        self._run_checks(exploded=out, demand=demand, spans=spans)

    def _run_checks(self, exploded=None, demand=None, spans=None):
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

        # Deduplicated on the REASON, not the label: one wrong thickness
        # on one section line produces a piece per frame member per
        # panel, and twelve copies of the same sentence is how a real
        # warning gets scrolled past.
        reasons = set()
        for values in (exploded or []):
            if not values.get('missing_product'):
                continue
            reason = values.get('missing_product_reason')
            if reason:
                reasons.add(reason)
            else:
                problems.append(('warning', _(
                    "No product for '%s'.", values.get('label') or '')))
        # ERROR, not a warning, since phase 7e. The commonest cause is now
        # a finish the profile is not sold in, and that is not a thing to
        # look at later: the window cannot be made as quoted, and the
        # piece would go on the cut list with no product and no price.
        # The reason already names the profile, the value and what IS
        # available.
        for reason in sorted(reasons):
            problems.append(('error', reason))

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

        # Pricing (spec 8). An incomplete price must never be mistaken
        # for a real one, so the lines that carry no cost are named
        # rather than quietly averaged into a number that looks fine.
        uncosted = self.bom_line_ids.filtered('cost_note')
        if uncosted:
            reasons = {}
            for line in uncosted:
                reasons.setdefault(line.cost_note, 0)
                reasons[line.cost_note] += 1
            for reason, count in sorted(reasons.items()):
                problems.append(('warning', _(
                    "%(count)s BOM line(s) have no cost: %(reason)s.",
                    count=count, reason=reason)))

        # A divider carrying more than its option is rated for. Never a
        # block: the shop may know better than the table, and the table
        # is seeded with 0 (no limit) anyway.
        for line, product, span in (spans or {}).values():
            limit = product.aw_max_span_mm
            if not limit or span <= limit:
                continue
            # Any profile the LINE offers with a higher rating, including
            # the default: the estimator may have switched to an
            # alternate that is lighter than what the spec starts with.
            # An unrated profile (0 = no limit) counts as adequate, which
            # is the same reading the warning itself uses.
            heavier = line._profile_choices().filtered(
                lambda other, p=product, s=span: (
                    other != p
                    and (not other.aw_max_span_mm
                         or other.aw_max_span_mm >= s)))
            problems.append(('warning', _(
                "A %(pos)s spans %(span)s, more than %(profile)s is "
                "rated for (%(max)s).%(advice)s",
                pos=line.position_id.name,
                span=self._format_length(span),
                profile=product.display_name,
                max=self._format_length(limit),
                advice=(_(" %s is rated for it.")
                        % ', '.join(heavier.mapped('display_name')))
                if heavier else '')))

        # Spec 9: sliding and opening panels need different outer
        # frames, so one frame cannot carry both.
        mixed = self._mixed_frame_error()
        if mixed:
            problems.append(('error', mixed))

        floor = self._min_margin_pct()
        if self._below_margin_floor():
            problems.append(('warning', _(
                "Margin is %(margin).2f%%, below the %(floor).2f%% "
                "minimum.", margin=self.margin_pct, floor=floor)))
        if self.bom_line_ids and not self.price_structure_id:
            problems.append(('warning', _(
                "No Price Structure, so this design is costed with no "
                "wastage, labour or profit.")))

        # ONCE per design, not once per hardware line that did not
        # appear: the absence is one fact about the spec, and a warning
        # repeated per line is a warning people learn to scroll past.
        # A spec may legitimately have no Hardware Set -- no hardware
        # list exists for this business yet, and a placeholder set
        # would put zero hardware into every quote while looking
        # configured. Saying so is the honest alternative.
        if not self._spec_hardware_lines():
            problems.append(('warning', _(
                "No hardware in this spec — hardware cost is missing.")))

        # No joints and no couplers: every piece comes out of one bar,
        # so one that cannot is a hard error rather than something the
        # optimiser works around.
        limit = self._max_piece_mm()
        for line in self.bom_line_ids:
            if line.kind == 'profile' and line.length_mm > limit:
                problems.append(('error', _(
                    "'%(label)s' is %(len)s, longer than the %(max)s that "
                    "can be cut from one bar. Reduce the size — pieces "
                    "are never joined.",
                    label=line.label or '',
                    len=self._format_length(line.length_mm),
                    max=self._format_length(limit))))

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
        lines = self._spec_profile_lines()
        if not lines:
            # One error beats one warning per position: the spec is the
            # thing to fix, and the rest would all say the same.
            return [('error', _(
                "%s has no profiles, so this design has none in its BOM "
                "at all.",
                self.template_id.display_name
                or _("No Specification is set, and so")))]

        configured = set(lines.mapped('position_id').ids)
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
                "'%(spec)s' has no '%(position)s' line "
                "(%(count)s %(what)s in this design).",
                spec=self.template_id.display_name, position=position.name,
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
