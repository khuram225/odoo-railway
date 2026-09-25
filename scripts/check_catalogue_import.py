#!/usr/bin/env python3
"""Dry-run the catalogue import against the real zip, without a database.

An import that half-works is expensive to undo: 196 products created
under the wrong category, or nine junk values added to the Thickness
attribute that then appear in every dropdown for ever. The join and the
classification can both be checked offline, so they are.

Uses the SAME normalisation and plausibility rules the wizard uses
(`aw_fenestration_core/models/thickness.py`), so this cannot drift from
what the import actually does.

The zip is vendor data and is not committed, so this skips cleanly when
it is absent.
"""
import csv
import importlib.util
import io
import re
import sys
import zipfile
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / 'odoo' / 'addons' / 'aw_fenestration_core'
ZIP = ROOT / 'chawla_catalogue_for_odoo.zip'

EXPECTED_UPDATED = 385
EXPECTED_CREATED = 196


def load_thickness():
    spec = importlib.util.spec_from_file_location(
        'thickness', CORE / 'models' / 'thickness.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seeded_names(filename, pattern):
    text = (CORE / 'data' / filename).read_text(encoding='utf-8')
    return {unescape(name) for name in re.findall(pattern, text)}


def main():
    if not ZIP.is_file():
        print('check_catalogue_import: %s not present, skipping '
              '(vendor data, not committed)' % ZIP.name)
        return 0

    thickness = load_thickness()
    archive = zipfile.ZipFile(ZIP)
    entries = set(archive.namelist())

    def rows(name):
        return list(csv.DictReader(
            io.StringIO(archive.read(name).decode('utf-8-sig'))))

    existing = rows('existing_products.csv')
    new = rows('new_products.csv')

    templates = seeded_names(
        'chawla_profiles_data.xml',
        r'<record id="aw_profile_tmpl_[^"]+" model="product\.template">\s*'
        r'<field name="name">([^<]*)</field>')
    attribute_values = seeded_names(
        'chawla_attributes_data.xml',
        r'<record id="aw_attr_val_thickness_[^"]+" '
        r'model="product\.attribute\.value">\s*'
        r'<field name="name">([^<]*)</field>')

    problems = []

    # ---- existing_products.csv only ever updates ----------------------
    names = [(row['product_name'] or '').strip() for row in existing]
    unmatched = sorted(set(names) - templates)
    if unmatched:
        problems.append(
            '%s row(s) in existing_products.csv match no product: %s'
            % (len(unmatched), ', '.join(unmatched[:5])))
    if len(existing) != EXPECTED_UPDATED:
        problems.append('existing_products.csv has %s rows, expected %s'
                        % (len(existing), EXPECTED_UPDATED))
    if len(names) != len(set(names)):
        problems.append('existing_products.csv repeats a product name')

    # ---- new_products.csv only ever creates ---------------------------
    new_names = [(row['product_name'] or '').strip() for row in new]
    collisions = sorted(set(new_names) & templates)
    if collisions:
        problems.append(
            '%s row(s) in new_products.csv already exist: %s'
            % (len(collisions), ', '.join(collisions[:5])))
    if len(new) != EXPECTED_CREATED:
        problems.append('new_products.csv has %s rows, expected %s'
                        % (len(new), EXPECTED_CREATED))
    lowered = [name.lower() for name in new_names]
    if len(lowered) != len(set(lowered)):
        problems.append('new_products.csv repeats a name (case-insensitively)')

    # ---- every referenced image is in the zip -------------------------
    for label, source in (('existing', existing), ('new', new)):
        missing = [row['image_file'] for row in source
                   if (row.get('image_file') or '').strip()
                   and row['image_file'] not in entries]
        if missing:
            problems.append('%s: %s image(s) referenced but not in the zip: %s'
                            % (label, len(missing), missing[:3]))

    # ---- pages are numbers --------------------------------------------
    for label, source in (('existing', existing), ('new', new)):
        bad = [row['catalogue_page'] for row in source
               if (row.get('catalogue_page') or '').strip()
               and not row['catalogue_page'].strip().isdigit()]
        if bad:
            problems.append('%s: non-numeric catalogue_page %s'
                            % (label, bad[:3]))

    # ---- thickness values: what is created, and what is refused -------
    rejected, created_values = [], set()
    for row in new:
        for raw in (row.get('thickness_values') or '').split(';'):
            canonical = thickness.norm_thickness(raw)
            if not canonical:
                continue
            if thickness.implausible_thickness(canonical):
                rejected.append((row['product_name'].strip(), canonical))
            elif canonical not in attribute_values:
                created_values.add(canonical)

    # The two known-bad rows. If this list ever shrinks the rule has gone
    # soft; if it grows, new junk arrived and wants looking at.
    expected_rejects = {'130MM', '2300MM', '50MM'}
    got_rejects = {value for _name, value in rejected}
    if got_rejects != expected_rejects:
        problems.append(
            'rejected thicknesses are %s, expected %s -- either the '
            'plausibility rule moved or the data changed'
            % (sorted(got_rejects), sorted(expected_rejects)))

    if problems:
        print('Catalogue import problems:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('Catalogue import dry run: %s to update (all matched), %s to '
          'create (no collisions), %s image(s) present, %s new thickness '
          'value(s), %s refused as not a thickness (%s).'
          % (len(existing), len(new),
             len([n for n in entries if n.endswith('.webp')]),
             len(created_values), len(rejected),
             ', '.join('%s on %s' % (v, n) for n, v in rejected)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
