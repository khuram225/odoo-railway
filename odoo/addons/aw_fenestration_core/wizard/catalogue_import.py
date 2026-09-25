# -*- coding: utf-8 -*-
"""Import the Chawla catalogue: pictures, codes, pages, sections.

Two files in one zip, doing two different jobs, and the distinction is
the point:

- `existing_products.csv` only ever UPDATES. Every row matched a
  product template by exact name when this was written (385 of 385),
  and a row that does not match is reported rather than created --
  creating from this file would quietly duplicate a profile under a
  slightly different spelling.
- `new_products.csv` only ever CREATES, and skips any name that
  already exists.

Images are WebP and are stored as they are. Verified against
odoo-src: `ImageProcess.__init__` sets `self.image = False` for WebP
after checking its resolution, and `image_quality()` opens with
`if not self.image: return self.source`, so `image_1920` keeps the
bytes verbatim. The resized variants are the same bytes rather than
genuine thumbnails, which is harmless at ~4 KB each.
"""
import base64
import csv
import io
import logging
import zipfile
from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.thickness import implausible_thickness, norm_thickness

_logger = logging.getLogger(__name__)

EXISTING_COLUMNS = {'product_name', 'image_file', 'catalogue_code',
                    'catalogue_category', 'catalogue_page',
                    'section_dims_mm', 'catalogue_thickness'}
NEW_COLUMNS = {'product_name', 'catalogue_code', 'catalogue_category',
               'catalogue_page', 'section_dims_mm', 'thickness_values',
               'image_file'}


class AwCatalogueImport(models.TransientModel):
    _name = 'aw.catalogue.import'
    _description = 'Import Fenestration Catalogue'

    file_data = fields.Binary(string='Catalogue (ZIP)', required=True)
    file_name = fields.Char()
    overwrite_images = fields.Boolean(
        string='Overwrite existing pictures',
        help="Off by default: a picture someone has already chosen is "
             "not replaced by a re-import.")
    state = fields.Selection([
        ('choose', 'Choose'),
        ('done', 'Done'),
    ], default='choose')
    summary = fields.Html(readonly=True)

    # ------------------------------------------------------------------
    def _open(self):
        self.ensure_one()
        try:
            archive = zipfile.ZipFile(
                io.BytesIO(base64.b64decode(self.file_data)))
        except (zipfile.BadZipFile, ValueError) as error:
            raise UserError(_("That file is not a readable zip: %s", error))
        names = set(archive.namelist())
        for required in ('existing_products.csv', 'new_products.csv'):
            if required not in names:
                raise UserError(_(
                    "The zip has no %s. Expected the catalogue export with "
                    "existing_products.csv, new_products.csv and their "
                    "images folders.", required))
        return archive

    @staticmethod
    def _rows(archive, name, required_columns):
        text = archive.read(name).decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise UserError(_(
                "%(file)s is missing column(s): %(cols)s",
                file=name, cols=', '.join(sorted(missing))))
        return list(reader)

    @staticmethod
    def _image(archive, path):
        if not path:
            return False
        try:
            return base64.b64encode(archive.read(path))
        except KeyError:
            return False

    @staticmethod
    def _catalogue_values(row):
        page = (row.get('catalogue_page') or '').strip()
        return {
            'aw_catalogue_code': (row.get('catalogue_code') or '').strip(),
            'aw_catalogue_category': (
                row.get('catalogue_category') or '').strip(),
            'aw_catalogue_page': int(page) if page.isdigit() else 0,
            'aw_section_dims': (row.get('section_dims_mm') or '').strip(),
        }

    # ------------------------------------------------------------------
    def action_import(self):
        self.ensure_one()
        archive = self._open()
        existing_rows = self._rows(
            archive, 'existing_products.csv', EXISTING_COLUMNS)
        new_rows = self._rows(archive, 'new_products.csv', NEW_COLUMNS)

        report = defaultdict(list)
        touched = self._import_existing(archive, existing_rows, report)
        self._import_new(archive, new_rows, report)

        # The catalogue lists thicknesses the price list does not, so
        # they are added to the Thickness attribute line as well as
        # recorded as text. Union only -- see
        # _aw_merge_catalogue_thickness.
        added, refused = touched._aw_merge_catalogue_thickness()
        for template, names in added.items():
            report['thickness_added'].append(
                '%s: %s' % (template.name, ', '.join(sorted(names))))
        for template, names in refused.items():
            report['bad_thickness'].extend(
                '%s: %s' % (template.name, name) for name in names)

        self.write({'state': 'done', 'summary': self._summary(report)})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    # ------------------------------------------------------------------
    def _import_existing(self, archive, rows, report):
        Template = self.env['product.template']
        # One query for every name, rather than one per row.
        wanted = [(row.get('product_name') or '').strip() for row in rows]
        by_name = {}
        for template in Template.search([('name', 'in', wanted)]):
            by_name.setdefault(template.name, template)
        touched = Template.browse()

        for row in rows:
            name = (row.get('product_name') or '').strip()
            template = by_name.get(name)
            if not template:
                report['not_found'].append(name)
                continue

            values = self._catalogue_values(row)
            values['aw_catalogue_thickness'] = (
                row.get('catalogue_thickness') or '').strip()

            image = self._image(archive, (row.get('image_file') or '').strip())
            if image and (self.overwrite_images or not template.image_1920):
                values['image_1920'] = image
            elif image and template.image_1920:
                report['image_kept'].append(name)

            template.write(values)
            touched |= template
            report['updated'].append(name)

        return touched

    # ------------------------------------------------------------------
    def _import_new(self, archive, rows, report):
        Template = self.env['product.template']
        # Every existing name, lowercased, in ONE query. Case-insensitive
        # because two profiles whose names differ only in case are the
        # same profile, and a per-row =ilike would be 196 queries.
        existing_names = {
            (record['name'] or '').strip().lower()
            for record in Template.with_context(active_test=False).search_read(
                [], ['name'])
        }

        thickness_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_thickness')
        finish_attr = self.env.ref(
            'aw_fenestration_core.aw_attribute_finish')
        finish_values = self.env['product.attribute.value'].search(
            [('attribute_id', '=', finish_attr.id)])
        uom_meter = self.env.ref('uom.product_uom_meter')

        thickness_cache = {
            value.name: value
            for value in self.env['product.attribute.value'].search(
                [('attribute_id', '=', thickness_attr.id)])}
        category_cache = {}

        batch = []
        for row in rows:
            name = (row.get('product_name') or '').strip()
            if not name:
                continue
            if name.lower() in existing_names:
                report['skipped'].append(name)
                continue

            category = self._category_for(
                (row.get('catalogue_category') or '').strip(), category_cache)

            wanted_thickness = self.env['product.attribute.value']
            for raw in (row.get('thickness_values') or '').split(';'):
                canonical = norm_thickness(raw)
                if not canonical:
                    continue
                if implausible_thickness(canonical):
                    # A length or a section dimension in the wrong
                    # column. Reported, never turned into an attribute
                    # value that would then haunt every dropdown.
                    report['bad_thickness'].append(
                        '%s: %s' % (name, canonical))
                    continue
                value = thickness_cache.get(canonical)
                if not value:
                    value = self.env['product.attribute.value'].create({
                        'name': canonical,
                        'attribute_id': thickness_attr.id,
                    })
                    thickness_cache[canonical] = value
                    report['new_thickness'].append(canonical)
                wanted_thickness |= value

            lines = []
            if wanted_thickness:
                lines.append((0, 0, {
                    'attribute_id': thickness_attr.id,
                    'value_ids': [(6, 0, wanted_thickness.ids)],
                }))
            else:
                report['no_thickness'].append(name)
            if finish_values:
                lines.append((0, 0, {
                    'attribute_id': finish_attr.id,
                    'value_ids': [(6, 0, finish_values.ids)],
                }))

            values = self._catalogue_values(row)
            values['aw_catalogue_thickness'] = (
                row.get('thickness_values') or '').strip()
            values.update({
                'name': name,
                'type': 'consu',
                'is_storable': True,
                'uom_id': uom_meter.id,
                'categ_id': category.id,
                'sale_ok': False,
                'purchase_ok': True,
                'attribute_line_ids': lines,
                'description': (row.get('note') or '').strip() or False,
                'image_1920': self._image(
                    archive, (row.get('image_file') or '').strip()),
            })
            batch.append(values)
            existing_names.add(name.lower())
            report['created'].append(name)

        if batch:
            # One create for the whole file rather than 196 of them.
            Template.create(batch)

    def _category_for(self, label, cache):
        """Fenestration / Profiles / <catalogue_category>, made if new."""
        if label in cache:
            return cache[label]
        parent = self.env.ref(
            'aw_fenestration_core.product_category_profiles')
        if not label:
            cache[label] = parent
            return parent
        category = self.env['product.category'].search([
            ('name', '=', label), ('parent_id', '=', parent.id),
        ], limit=1)
        if not category:
            category = self.env['product.category'].create({
                'name': label, 'parent_id': parent.id,
            })
        cache[label] = category
        return category

    # ------------------------------------------------------------------
    def _summary(self, report):
        def block(title, items, tone='', limit=60):
            if not items:
                return ''
            shown = items[:limit]
            more = ('<li><em>… and %s more</em></li>' % (len(items) - limit)
                    if len(items) > limit else '')
            return ('<h4 class="%s">%s (%s)</h4><ul>%s%s</ul>' % (
                tone, title, len(items),
                ''.join('<li>%s</li>' % item for item in shown), more))

        parts = [
            '<h3>%s updated · %s created · %s skipped · %s not found</h3>' % (
                len(report['updated']), len(report['created']),
                len(report['skipped']), len(report['not_found'])),
        ]
        parts.append(block('Not found — no product with this name',
                           report['not_found'], 'text-danger'))
        parts.append(block(
            'Rejected as a thickness — a length or section dimension in '
            'the wrong column, so NOT created as an attribute value',
            report['bad_thickness'], 'text-danger'))
        parts.append(block('Created with no thickness at all',
                           report['no_thickness'], 'text-warning'))
        parts.append(block('Existing picture kept (overwrite is off)',
                           report['image_kept'], 'text-muted'))
        parts.append(block('New thickness values created',
                           report['new_thickness']))
        parts.append(block('Thickness values added to the product',
                           report['thickness_added']))
        parts.append(block('Skipped — a product of this name already exists',
                           report['skipped'], 'text-muted'))
        parts.append(block('Created', report['created'], 'text-muted'))
        parts.append(block('Updated', report['updated'], 'text-muted'))
        return ''.join(part for part in parts if part)
