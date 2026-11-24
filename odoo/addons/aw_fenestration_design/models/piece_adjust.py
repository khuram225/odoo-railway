# -*- coding: utf-8 -*-
"""A +/- adjustment on one piece of one window.

A piece's length comes from the spec's rule (W, H, PW - 10, ...). Sometimes
the workshop cuts one piece a little differently: 3 soot shorter, 1 in
longer. That is an ADJUSTMENT, a number added after the rule, so it follows
the window when its size changes (an absolute length typed on the piece
would not).

  final length = rule length + adjustment

Rules this keeps, all of them tested:

* It is keyed by the piece's `piece_key` (spec line | panel | unit | ordinal),
  the same key a typed length is found again by, so a resize or a
  recompute does not lose it.
* A typed ABSOLUTE length still wins: it is applied after the explosion, over
  whatever the rule and the adjustment gave.
* No cascade: an adjustment changes its own piece only. A sash is not moved
  by a frame adjustment, whatever the formulas say.
* Replace semantics: a row is the FINAL adjustment for that piece. No row
  follows the series default, which is zero until the Size rules page
  exists (`_adjust_default_mm` is where it will come from).
* `computed_length_mm` on the BOM line is the rule length plus the
  adjustment, i.e. the length before anything was typed on the piece. The
  rule length alone is `computed_length_mm - adjustment`.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# An adjustment is a few inches at most. Anything above this is a typo
# (a length typed where an adjustment was meant), not a cut.
MAX_ADJUST_MM = 1000.0


class AwDesignPieceAdjust(models.Model):
    _name = 'aw.design.piece.adjust'
    _description = 'Fenestration Piece Length Adjustment'
    _order = 'design_id, piece_key'

    design_id = fields.Many2one(
        'aw.design', required=True, ondelete='cascade', index=True)
    piece_key = fields.Char(
        required=True, index=True,
        help="Which piece: spec line, panel, unit and ordinal, as on the "
             "BOM line.")
    adjust_mm = fields.Float(
        string='Adjustment (mm)',
        help="Added to the rule's length. Negative cuts shorter.")

    @api.constrains('design_id', 'piece_key')
    def _check_one_per_piece(self):
        for rec in self:
            if self.search_count([('design_id', '=', rec.design_id.id),
                                  ('piece_key', '=', rec.piece_key)]) > 1:
                raise ValidationError(_(
                    "A piece has one adjustment. Change that one."))


class AwDesign(models.Model):
    _inherit = 'aw.design'

    piece_adjust_ids = fields.One2many(
        'aw.design.piece.adjust', 'design_id', string='Piece adjustments')

    def _piece_adjustments(self):
        """{piece_key: mm} of this window's own adjustments."""
        self.ensure_one()
        return {a.piece_key: a.adjust_mm for a in self.piece_adjust_ids}

    def _adjust_default_mm(self, template_line_id):
        """What a piece with no adjustment of its own gets: the series
        default for its spec line. Zero until the Size rules page exists."""
        return 0.0

    def _adjustable_line(self, piece_key):
        """The BOM line a piece key names, if it can be adjusted: a
        generated profile piece with a length (not cut on site, not added by
        hand, which has no rule to add to)."""
        self.ensure_one()
        return self.bom_line_ids.filtered(
            lambda l: l.piece_key == piece_key and l.kind == 'profile'
            and not l.cut_on_site and not l.is_free_form
            and l.template_line_id)[:1]

    def _rule_length(self, line, adjustments=None):
        """The spec's rule length of a piece: its computed length less the
        adjustment that is in it."""
        adjustments = (adjustments if adjustments is not None
                       else self._piece_adjustments())
        shift = adjustments.get(line.piece_key)
        if shift is None:
            shift = self._adjust_default_mm(line.template_line_id.id)
        return (line.computed_length_mm or 0.0) - shift

    def set_piece_adjustment(self, piece_key, mm):
        """Set a piece's adjustment (the final one for that piece), then
        recompute the window so the cut list shows it."""
        self.ensure_one()
        line = self._adjustable_line(piece_key)
        if not line:
            raise UserError(_("That piece cannot be adjusted."))
        try:
            mm = float(mm)
        except (TypeError, ValueError):
            raise UserError(_("That adjustment cannot be read."))
        if mm != mm or abs(mm) > MAX_ADJUST_MM:        # nan, or a typo
            raise UserError(_(
                "An adjustment is a few inches at most. To set the length "
                "itself, type it in the length box."))
        rule = self._rule_length(line)
        if rule + mm <= 0:
            raise UserError(_(
                "That adjustment would make the piece 0 long or less."))
        row = self.piece_adjust_ids.filtered(
            lambda a: a.piece_key == piece_key)
        # The explosion below replaces every BOM line: read what the note
        # needs first.
        ref, label = line.piece_ref or piece_key, line.label or ''
        if row:
            row.adjust_mm = mm
        else:
            self.env['aw.design.piece.adjust'].create({
                'design_id': self.id, 'piece_key': piece_key,
                'adjust_mm': mm})
        self._explode()
        self.message_post(body=_(
            "%(who)s adjusted piece %(ref)s (%(label)s) by %(mm)+.2f mm: "
            "rule %(rule).1f mm, now %(now).1f mm.",
            who=self.env.user.name, ref=ref, label=label,
            mm=mm, rule=rule, now=rule + mm))
        return self.get_configurator_data()

    def reset_piece_adjustment(self, piece_key):
        """Delete a piece's own adjustment: it follows the series default
        (zero for now) again."""
        self.ensure_one()
        row = self.piece_adjust_ids.filtered(
            lambda a: a.piece_key == piece_key)
        if row:
            ref = self.bom_line_ids.filtered(
                lambda l: l.piece_key == piece_key)[:1].piece_ref or piece_key
            row.unlink()
            self._explode()
            self.message_post(body=_(
                "%(who)s reset the adjustment of piece %(ref)s to the "
                "series default.", who=self.env.user.name, ref=ref))
        return self.get_configurator_data()

    @staticmethod
    def _position_of_key(piece_key):
        """(spec line, unit, ordinal) of a piece key, which is spec line |
        panel | unit | ordinal: the piece's place WITHOUT the panel, so the
        same piece of two panels has the same position. None if unreadable."""
        parts = (piece_key or '').split('|')
        if len(parts) != 4:
            return None
        return (parts[0], parts[2], parts[3])

    def copy_piece_adjustments(self, from_panel, to_panel):
        """Copy panel `from_panel`'s adjustments onto panel `to_panel`, piece
        by piece, where the other panel has a piece in the SAME position (same
        spec line, unit and ordinal; the panel type is not looked at). A
        matched piece takes the source's adjustment and replaces its own; the
        target's other pieces are left alone. A source adjustment with no
        matching piece is skipped; one that would make its piece 0 long, or is
        over the limit, is refused and counted apart. Nothing is written when
        nothing can be copied. Returns the configurator data and the counts."""
        self.ensure_one()
        from_panel, to_panel = int(from_panel or 0), int(to_panel or 0)
        if not from_panel or not to_panel or from_panel == to_panel:
            raise UserError(_("Choose another panel to copy from."))
        adjustments = self._piece_adjustments()
        source = {}
        for key, mm in adjustments.items():
            parts = key.split('|')
            if len(parts) == 4 and parts[1] == str(from_panel):
                source[self._position_of_key(key)] = mm
        targets = {}
        for line in self.bom_line_ids:
            if (line.panel_no or 0) != to_panel:
                continue
            if not self._adjustable_line(line.piece_key):
                continue
            targets[self._position_of_key(line.piece_key)] = line
        copied = refused = 0
        todo = []
        for position, mm in source.items():
            line = targets.get(position)
            if line is None:
                continue
            if abs(mm) > MAX_ADJUST_MM or self._rule_length(
                    line, adjustments) + mm <= 0:
                refused += 1
                continue
            todo.append((line.piece_key, mm))
            copied += 1
        skipped = len(source) - copied - refused
        result = {'copied': copied, 'skipped': skipped, 'refused': refused}
        if copied:
            Adjust = self.env['aw.design.piece.adjust']
            for piece_key, mm in todo:
                row = self.piece_adjust_ids.filtered(
                    lambda a: a.piece_key == piece_key)
                if row:
                    row.adjust_mm = mm
                else:
                    Adjust.create({'design_id': self.id,
                                   'piece_key': piece_key, 'adjust_mm': mm})
            self._explode()
            self.message_post(body=_(
                "%(who)s copied the adjustments of panel %(src)s to panel "
                "%(dst)s: copied %(copied)s, skipped %(skipped)s (no piece in "
                "the same position)%(refused)s.",
                who=self.env.user.name, src=from_panel, dst=to_panel,
                copied=copied, skipped=skipped,
                refused=(_(", refused %s (would make the piece 0 long)",
                           refused) if refused else '')))
        result['data'] = self.get_configurator_data()
        return result
