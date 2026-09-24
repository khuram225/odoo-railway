# -*- coding: utf-8 -*-
"""The stored elevation drawing (spec 7) and what the reports read.

The drawing on a shop drawing has to be the drawing the shop was shown,
not one regenerated later from possibly-changed data. So the
configurator hands the server the SVG it actually rendered, plus a PNG
rasterised from it in the browser, and the design keeps both along with
a fingerprint of the layout they were taken from. If the layout moves
afterwards -- someone edits width on the form, say -- the fingerprint
stops matching and every report says so instead of printing a drawing
that quietly lies about the product.

Why a PNG as well as the SVG: reports render through wkhtmltopdf, whose
engine is an old QtWebKit with patchy inline-SVG support. The PNG is
what the PDFs embed; the SVG is kept because it is the lossless
original and is what a future HTML-based renderer would want.
"""
import hashlib
import json

from odoo import _, api, fields, models


class AwDesign(models.Model):
    _inherit = 'aw.design'

    elevation_svg = fields.Text(
        string='Elevation (SVG)', readonly=True, copy=False,
        help="The drawing exactly as the configurator rendered it.")
    elevation_png = fields.Binary(
        string='Elevation (PNG)', readonly=True, copy=False, attachment=True,
        help="Rasterised in the browser from the SVG. This is what the "
             "PDF reports embed.")
    elevation_hash = fields.Char(
        readonly=True, copy=False,
        help="Fingerprint of the layout the drawing was taken from.")
    elevation_date = fields.Datetime(readonly=True, copy=False)
    elevation_is_current = fields.Boolean(
        compute='_compute_elevation_is_current',
        help="False when the layout changed after the drawing was taken.")

    # ------------------------------------------------------------------
    # fingerprint
    # ------------------------------------------------------------------
    def _layout_fingerprint(self):
        """A stable digest of everything the drawing shows.

        Deliberately covers what is VISIBLE, not every field: size, the
        row/leaf tree, each panel's type and direction, and the
        attachments that are drawn. Glass spec is in it because the
        panel schedule prints it. A change to something the drawing
        cannot show -- the hardware set, say -- does not invalidate it,
        because reprinting would produce an identical picture and a
        false "out of date" is its own kind of wrong.
        """
        self.ensure_one()

        def leaves(rows):
            out = []
            for row in rows.sorted(lambda r: (r.sequence, r.id)):
                panels = []
                for leaf in row.leaf_ids.sorted(lambda l: (l.sequence, l.id)):
                    panels.append({
                        'w': round(leaf.width_mm or 0.0, 3),
                        'type': leaf.leaf_type_id.code or '',
                        'hinge': leaf.hinge_side or '',
                        'swing': leaf.swing or '',
                        'slide': leaf.slide_dir or '',
                        'track': leaf.track_no or 0,
                        'junction': leaf.junction_after or '',
                        'mesh': leaf.mesh_type_id.id or 0,
                        'infill': leaf.infill_type_id.id or 0,
                        'grid': leaf.grid_pattern_id.id or 0,
                        'grid_rc': [leaf.grid_rows or 0, leaf.grid_cols or 0],
                        'glass': leaf.glass_spec_id.id or 0,
                        'panel_no': leaf.panel_no or 0,
                        'rows': leaves(leaf.child_row_ids),
                    })
                out.append({
                    'h': round(row.height_mm or 0.0, 3), 'leaves': panels})
            return out

        payload = {
            'w': round(self.width_mm or 0.0, 3),
            'h': round(self.height_mm or 0.0, 3),
            'glass': self.glass_spec_id.id or 0,
            'rows': leaves(self.row_ids),
        }
        # sort_keys so an unrelated dict ordering change can never look
        # like a layout change.
        blob = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()

    @api.depends('width_mm', 'height_mm', 'glass_spec_id', 'elevation_hash',
                 'elevation_svg',
                 'row_ids.height_mm', 'row_ids.leaf_ids.width_mm',
                 'row_ids.leaf_ids.leaf_type_id',
                 'row_ids.leaf_ids.hinge_side', 'row_ids.leaf_ids.swing',
                 'row_ids.leaf_ids.slide_dir', 'row_ids.leaf_ids.track_no',
                 'row_ids.leaf_ids.junction_after',
                 'row_ids.leaf_ids.mesh_type_id',
                 'row_ids.leaf_ids.infill_type_id',
                 'row_ids.leaf_ids.grid_pattern_id',
                 'row_ids.leaf_ids.glass_spec_id')
    def _compute_elevation_is_current(self):
        for design in self:
            design.elevation_is_current = bool(
                design.elevation_svg
                and design.elevation_hash == design._layout_fingerprint())

    def _store_elevation(self, snapshot):
        """Keep the drawing the configurator just rendered.

        Called from save_layout AFTER the rows are rebuilt and renumbered,
        so the fingerprint is taken from what is actually stored rather
        than from what the client believed it was sending.
        """
        self.ensure_one()
        svg = (snapshot or {}).get('svg')
        if not svg:
            return
        self.write({
            'elevation_svg': svg,
            # The client sends base64 with no data: prefix. A browser
            # that refuses to rasterise (canvas blocked) still gets the
            # SVG saved rather than failing the whole save.
            'elevation_png': (snapshot or {}).get('png') or False,
            'elevation_hash': self._layout_fingerprint(),
            'elevation_date': fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # what the reports read
    # ------------------------------------------------------------------
    def _elevation_warning(self):
        """One sentence, or empty. Used by both reports so they cannot
        disagree about whether the drawing is trustworthy."""
        self.ensure_one()
        if not self.elevation_svg:
            return _("No drawing yet — open this position in the "
                     "configurator and save.")
        if not self.elevation_is_current:
            return _("Drawing out of date — open in configurator and save.")
        return ''

    def _report_panels(self):
        """The panel schedule: every real panel, containers skipped."""
        self.ensure_one()
        rows = []

        def direction(leaf):
            bits = []
            if leaf.leaf_type_id.has_hinge_side:
                if leaf.hinge_side:
                    bits.append(_("hinge %s") % leaf.hinge_side)
                if leaf.swing:
                    bits.append(_("opens %s") % leaf.swing)
            if leaf.leaf_type_id.has_slide_dir:
                if leaf.slide_dir:
                    bits.append(_("slides %s") % leaf.slide_dir)
                if leaf.track_no:
                    bits.append(_("track %s") % leaf.track_no)
            return ', '.join(bits)

        def walk(row_set, box_h):
            for row in row_set.sorted(lambda r: (r.sequence, r.id)):
                for leaf in row.leaf_ids.sorted(lambda l: (l.sequence, l.id)):
                    if leaf.child_row_ids:
                        walk(leaf.child_row_ids, row.height_mm)
                        continue
                    rows.append({
                        'panel_no': leaf.panel_no or 0,
                        'type': leaf.leaf_type_id.display_name or '',
                        'direction': direction(leaf),
                        'size': '%s x %s' % (
                            self._format_length(leaf.width_mm or 0.0),
                            self._format_length(row.height_mm or 0.0)),
                        'glass': (leaf.glass_spec_id
                                  or self.glass_spec_id).display_name or '',
                        'mesh': leaf.mesh_type_id.display_name or '',
                        'infill': leaf.infill_type_id.display_name or '',
                        'grid': leaf.grid_pattern_id.display_name or '',
                    })

        walk(self.row_ids, self.height_mm)
        return sorted(rows, key=lambda r: r['panel_no'])

    def _report_bom(self, kinds):
        """BOM lines of the given kinds, in print order."""
        self.ensure_one()
        return self.bom_line_ids.filtered(
            lambda l: l.kind in kinds).sorted(
                lambda l: (l.sequence, l.id))

    def _panel_summary(self):
        """One short line for the customer PDF: '2 Slider, 1 Fixed'."""
        self.ensure_one()
        counts = {}
        for panel in self._report_panels():
            counts[panel['type']] = counts.get(panel['type'], 0) + 1
        return ', '.join('%s %s' % (n, name)
                         for name, n in sorted(counts.items()))

    def action_print_shop_drawing(self):
        return self.env.ref(
            'aw_fenestration_design.action_report_aw_shop_drawing'
        ).report_action(self)
