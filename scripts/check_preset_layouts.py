#!/usr/bin/env python3
"""Validate every seeded layout_json with the SAME rules the upgrade uses.

Why this exists: OPN-VNT was the first seeded preset containing a nested
container, and `aw.layout.preset._check_layout_json` assumed every leaf
carried a leaf type. The module upgrade died with

    ParseError ... "Layout of 'Fixed with top vent' uses unknown leaf
    type code None"

and nothing caught it beforehand, because every check in this repo runs
against the OWL component -- client-side JavaScript -- while this is a
server-side data rule applied at install time. The client happily
rendered the same preset, since its own code already skipped containers.

So this imports the real validator out of
aw_fenestration_design/models/layout_rules.py (kept free of Odoo imports
for exactly this reason), reads the leaf type codes out of the seed XML,
and runs the two against every preset record in the data files. If it
passes, the upgrade's constraint passes.

Usage:
    python scripts/check_preset_layouts.py
"""
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN = REPO_ROOT / 'odoo' / 'addons' / 'aw_fenestration_design'
CORE = REPO_ROOT / 'odoo' / 'addons' / 'aw_fenestration_core'


def load_rules():
    """Import layout_rules.py directly, without importing Odoo."""
    path = DESIGN / 'models' / 'layout_rules.py'
    spec = importlib.util.spec_from_file_location('layout_rules', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seeded_leaf_type_codes():
    codes = set()
    for xml_file in (CORE / 'data').glob('*.xml'):
        for record in ET.parse(xml_file).iter('record'):
            if record.get('model') != 'aw.leaf.type':
                continue
            field = record.find("field[@name='code']")
            if field is not None and field.text:
                codes.add(field.text.strip())
    return codes


def seeded_codes(model):
    """Codes seeded for a model, read out of this module's data files."""
    codes = set()
    for xml_file in (DESIGN / 'data').glob('*.xml'):
        for record in ET.parse(xml_file).iter('record'):
            if record.get('model') != model:
                continue
            field = record.find("field[@name='code']")
            if field is not None and field.text:
                codes.add(field.text.strip())
    return codes


def seeded_presets():
    for xml_file in sorted((DESIGN / 'data').glob('*.xml')):
        for record in ET.parse(xml_file).iter('record'):
            if record.get('model') != 'aw.layout.preset':
                continue
            layout = record.find("field[@name='layout_json']")
            if layout is None:
                continue
            name = record.find("field[@name='name']")
            yield (
                xml_file.name,
                record.get('id'),
                name.text if name is not None else record.get('id'),
                layout.text or '',
            )


def _nested(levels):
    """A layout nested `levels` deep, built rather than written out --
    the hand-written version was unreadable and its brackets were wrong."""
    layout = {'rows': [{'h': 1, 'leaves': [{'w': 1, 'type': 'FIXED'}]}]}
    for _ in range(levels - 1):
        layout = {'rows': [{'h': 1, 'leaves': [
            {'w': 1, 'rows': layout['rows']}]}]}
    return layout


def self_test(rules):
    """Exercise the rules themselves, not just the seed data.

    Seed data that happens to be valid proves nothing about a validator
    that is too lax -- the old one accepted plenty and rejected the one
    case that mattered. These cases pin the container rule down in both
    directions.
    """
    known = {'FIXED', 'CASEMENT', 'AWNING'}
    cases = [
        (True, 'plain panel',
         {'rows': [{'h': 1, 'leaves': [{'w': 1, 'type': 'FIXED'}]}]}),
        (True, 'container with sub-rows and no type',
         {'rows': [{'h': 1, 'leaves': [{'w': 1, 'rows': [
             {'h': 1, 'leaves': [{'w': 1, 'type': 'AWNING'}]},
             {'h': 3, 'leaves': [{'w': 1, 'type': 'FIXED'}]}]}]}]}),
        (False, 'container that also carries a type',
         {'rows': [{'h': 1, 'leaves': [{'w': 1, 'type': 'FIXED', 'rows': [
             {'h': 1, 'leaves': [{'w': 1, 'type': 'FIXED'}]}]}]}]}),
        (False, 'panel with no type at all',
         {'rows': [{'h': 1, 'leaves': [{'w': 1}]}]}),
        (False, 'panel with an unknown type',
         {'rows': [{'h': 1, 'leaves': [{'w': 1, 'type': 'NOPE'}]}]}),
        (False, 'empty rows',
         {'rows': []}),
        (False, 'row with no leaves',
         {'rows': [{'h': 1, 'leaves': []}]}),
        (False, 'nested four levels deep', _nested(4)),
    ]
    failures = []
    for should_pass, label, data in cases:
        errors = rules.validate_layout(data, known)
        if should_pass and errors:
            failures.append(f'{label}: expected valid, got {errors[0]}')
        elif not should_pass and not errors:
            failures.append(f'{label}: expected rejection, got none')

    # The Series filter has to see through containers too.
    nested = cases[1][2]
    codes = rules.leaf_type_codes(nested)
    if codes != {'AWNING', 'FIXED'}:
        failures.append(
            f'leaf_type_codes on a nested layout gave {codes}, '
            f'expected {{AWNING, FIXED}}')
    return failures


def main():
    rules = load_rules()

    failures = self_test(rules)
    if failures:
        print('The layout rules themselves are wrong:')
        for failure in failures:
            print(f'  {failure}')
        return 1

    known = seeded_leaf_type_codes()
    if not known:
        print('No aw.leaf.type codes found in the core seed data.')
        return 1

    mesh_codes = seeded_codes('aw.mesh.type')
    infill_codes = seeded_codes('aw.infill.type')
    grid_codes = seeded_codes('aw.grid.pattern')

    problems = []
    checked = 0
    for filename, xmlid, name, raw in seeded_presets():
        checked += 1
        try:
            data = json.loads(raw)
        except ValueError as exc:
            problems.append(f'{filename}: {xmlid} ({name}): invalid JSON: {exc}')
            continue
        for error in rules.validate_layout(
                data, known,
                known_mesh=mesh_codes,
                known_infill=infill_codes,
                known_grid=grid_codes):
            problems.append(f'{filename}: {xmlid} ({name}): {error}')
        # A preset whose codes can't be resolved would be offered on no
        # Series at all, which is silent rather than loud.
        if not rules.leaf_type_codes(data):
            problems.append(
                f'{filename}: {xmlid} ({name}): no leaf types at all, so no '
                f'Series can ever host it'
            )

    if problems:
        print('Seeded preset layouts that the upgrade would reject:')
        for problem in problems:
            print(f'  {problem}')
        return 1
    print(f'Layout rules self-test passed; {checked} seeded preset '
          f'layout(s) valid against {len(known)} leaf type, '
          f'{len(mesh_codes)} mesh, {len(infill_codes)} infill and '
          f'{len(grid_codes)} grid code(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
