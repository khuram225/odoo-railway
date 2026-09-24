#!/usr/bin/env python3
"""
Regenerates the aw_fenestration_core Chawla import from the raw pricelist.

Step 1: rebuild the canonical melt CSV from the raw Chawla pricelist, with
thickness standardized to one spelling per concept.
Step 2: regenerate data/chawla_attributes_data.xml and
data/chawla_profiles_data.xml purely by reading that melt CSV -- the melt
is the single source of truth for the Odoo import, not the raw pricelist.

The raw pricelist and the melt output are external inputs/artifacts (not
committed to this repo -- vendor data), so their paths default to the
layout used when this was written but can be overridden:

    python scripts/rebuild_melt_and_import.py \\
        --source /path/to/chawla_pricelist_2026-01-01.csv \\
        --melted-out /path/to/chawla_pricelist_melted_2026-01-01.csv
"""
import argparse
import csv
import html
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_DIR = REPO_ROOT / 'odoo' / 'addons' / 'aw_fenestration_core'

DEFAULT_SRC = Path(r'C:\Clients\erp\chawla_pricelist_2026-01-01.csv')
DEFAULT_MELTED_OUT = Path(r'C:\Clients\erp\chawla_pricelist_melted_2026-01-01.csv')

FINISH_COLS = ['natural', 'h23_pc_ral', 'brown_pc_sahara', 'black_multi_ss_dull', 'designer', 'c_shine']
FINISH_LABELS = {
    'natural': 'Natural',
    'h23_pc_ral': 'H23 PC RAL',
    'brown_pc_sahara': 'Brown PC Sahara',
    'black_multi_ss_dull': 'Black Multi SS Dull',
    'designer': 'Designer',
    'c_shine': 'C-Shine',
}


def norm_thickness(raw):
    """Canonicalize a raw thickness string to one spelling per concept.
    Verified exhaustively against the 33 distinct raw strings in the
    source CSV: no lowercase 'mm', no space/comma variants, no
    trailing-zero numeric duplicates (e.g. no '1.60MM' alongside
    '1.6MM') exist beyond the Std/STD/Std. case already handled here.
    """
    raw = raw.strip()
    if raw == '-':
        return ''  # no thickness dimension applies to this profile
    if raw == 'Nor':
        return 'Normal'
    if raw in ('Std', 'STD', 'Std.'):
        return 'Standard'
    m = re.match(r'^(\d+(?:\.\d+)?)\s*MM?$', raw, re.IGNORECASE)
    if m:
        return f'{m.group(1)}MM'
    return raw  # unrecognized -- none expected, would be caught by review below


def classify(code):
    if re.match(r'^(DC|M)[- ]', code):
        return 'box'
    if re.match(r'^D-[345]', code):
        return 'hinged'
    if re.match(r'^CW[- ]', code):
        return 'curtain'
    if re.match(r'^GSL[- ]', code):
        return 'gsl'
    return 'unclassified'


def slug(code):
    return re.sub(r'[^a-zA-Z0-9]+', '_', code).strip('_').lower()


def xmlid_tmpl(code):
    return f'aw_profile_tmpl_{slug(code)}'


def xmlid_thickness_val(canon):
    return f'aw_attr_val_thickness_{slug(canon)}'


def xmlid_finish_val(col):
    return f'aw_attr_val_finish_{col}'


def esc(s):
    return html.escape(s, quote=True)


CATEGORY_XMLID = {
    'box': 'product_category_profiles_box',
    'hinged': 'product_category_profiles_hinged',
    'curtain': 'product_category_profiles_curtain',
    'gsl': 'product_category_profiles_gsl',
    'unclassified': 'product_category_profiles_unclassified',
}


def rebuild_melt(src: Path, melted_out: Path):
    rows = list(csv.DictReader(open(src, encoding='utf-8-sig')))
    melted = []
    for r in rows:
        code = r['profile_code'].strip()
        t_raw = r['thickness'].strip()
        t_norm = norm_thickness(t_raw)
        any_price = False
        for fcol in FINISH_COLS:
            val = r[fcol].strip()
            if val:
                any_price = True
                melted.append((code, t_raw, t_norm, fcol, val, r['effective_from']))
        if not any_price:
            # no finish has a price on this row at all -- still record it
            # with a blank finish so the (profile_code, thickness)
            # combination isn't silently dropped from the melt.
            melted.append((code, t_raw, t_norm, '', '', r['effective_from']))

    with open(melted_out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['profile_code', 'thickness_raw', 'thickness_normalized', 'finish', 'price_pkr', 'effective_from', 'uom_note'])
        for code, t_raw, t_norm, fcol, price, eff in melted:
            w.writerow([code, t_raw, t_norm, FINISH_LABELS.get(fcol, ''), price, eff,
                        'PKR per running foot; stock lengths 14/16/18 ft. '
                        'Confirmed by the client, not yet in writing from Chawla'])


def load_profiles(melted_out: Path):
    melt_rows = list(csv.DictReader(open(melted_out, encoding='utf-8')))
    finish_label_to_col = {v: k for k, v in FINISH_LABELS.items()}

    profiles = defaultdict(lambda: {'thicknesses': set(), 'finishes': set(), 'category': None})
    for r in melt_rows:
        code = r['profile_code']
        p = profiles[code]
        p['category'] = classify(code)
        t_norm = r['thickness_normalized']
        if t_norm:
            p['thicknesses'].add(t_norm)
        if r['finish']:
            p['finishes'].add(finish_label_to_col[r['finish']])
    return profiles


def write_attributes_data(profiles, module_dir: Path):
    all_thickness_values = sorted({v for p in profiles.values() for v in p['thicknesses']})

    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append('<odoo>')
    lines.append('    <data noupdate="1">')
    lines.append('')
    lines.append('        <!-- Thickness: Dynamic variant creation (see aw_fenestration_core Task 1) -->')
    lines.append('        <!-- Generated from chawla_pricelist_melted_2026-01-01.csv, the single -->')
    lines.append('        <!-- source of truth for this import, do not hand-edit, regenerate. -->')
    lines.append('        <record id="aw_attribute_thickness" model="product.attribute">')
    lines.append('            <field name="name">Thickness</field>')
    lines.append('            <field name="create_variant">dynamic</field>')
    lines.append('        </record>')
    lines.append('')
    for v in all_thickness_values:
        lines.append(f'        <record id="{xmlid_thickness_val(v)}" model="product.attribute.value">')
        lines.append(f'            <field name="name">{esc(v)}</field>')
        lines.append('            <field name="attribute_id" ref="aw_attribute_thickness"/>')
        lines.append('        </record>')
    lines.append('')
    lines.append('        <!-- Finish: Dynamic variant creation -->')
    lines.append('        <record id="aw_attribute_finish" model="product.attribute">')
    lines.append('            <field name="name">Finish</field>')
    lines.append('            <field name="create_variant">dynamic</field>')
    lines.append('        </record>')
    lines.append('')
    for col in FINISH_COLS:
        lines.append(f'        <record id="{xmlid_finish_val(col)}" model="product.attribute.value">')
        lines.append(f'            <field name="name">{esc(FINISH_LABELS[col])}</field>')
        lines.append('            <field name="attribute_id" ref="aw_attribute_finish"/>')
        lines.append('        </record>')
    lines.append('')
    lines.append('    </data>')
    lines.append('</odoo>')

    (module_dir / 'data' / 'chawla_attributes_data.xml').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return all_thickness_values


def write_profiles_data(profiles, module_dir: Path):
    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append('<odoo>')
    lines.append('    <data noupdate="1">')
    lines.append('')
    lines.append('        <!-- Fallback bucket for profile_codes that don\'t match a known -->')
    lines.append('        <!-- Window Type prefix rule. Left as-is per decision: revisit the -->')
    lines.append('        <!-- mapping later with real category scope, not on test data. -->')
    lines.append('        <record id="product_category_profiles_unclassified" model="product.category">')
    lines.append('            <field name="name">Unclassified</field>')
    lines.append('            <field name="parent_id" ref="product_category_profiles"/>')
    lines.append('        </record>')
    lines.append('')

    for code in sorted(profiles.keys()):
        p = profiles[code]
        tid = xmlid_tmpl(code)
        lines.append(f'        <record id="{tid}" model="product.template">')
        lines.append(f'            <field name="name">{esc(code)}</field>')
        lines.append(f'            <field name="categ_id" ref="{CATEGORY_XMLID[p["category"]]}"/>')
        lines.append('            <field name="uom_id" ref="uom.product_uom_meter"/>')
        # uom_po_id does not exist on product.template in this Odoo version --
        # purchase UoM moved to product.supplierinfo.product_uom_id, set per
        # vendor line. Nothing to set here until this import builds supplier
        # pricelists. Do not reintroduce this field on a future regen.
        lines.append('            <field name="is_storable" eval="True"/>')
        attr_line_parts = []
        if p['thicknesses']:
            th_refs = ','.join(f"ref('{xmlid_thickness_val(v)}')" for v in sorted(p['thicknesses']))
            attr_line_parts.append(
                "(0, 0, {'attribute_id': ref('aw_attribute_thickness'), "
                f"'value_ids': [(6, 0, [{th_refs}])]}})"
            )
        fin_refs = ','.join(f"ref('{xmlid_finish_val(v)}')" for v in sorted(p['finishes']))
        attr_line_parts.append(
            "(0, 0, {'attribute_id': ref('aw_attribute_finish'), "
            f"'value_ids': [(6, 0, [{fin_refs}])]}})"
        )
        eval_expr = '[' + ', '.join(attr_line_parts) + ']'
        lines.append(f'            <field name="attribute_line_ids" eval="{esc(eval_expr)}"/>')
        lines.append('        </record>')

    lines.append('')
    lines.append('    </data>')
    lines.append('</odoo>')

    (module_dir / 'data' / 'chawla_profiles_data.xml').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=DEFAULT_SRC,
                         help=f'Raw Chawla pricelist CSV (default: {DEFAULT_SRC})')
    parser.add_argument('--melted-out', type=Path, default=DEFAULT_MELTED_OUT,
                         help=f'Where to write the canonical melt CSV (default: {DEFAULT_MELTED_OUT})')
    parser.add_argument('--module-dir', type=Path, default=MODULE_DIR,
                         help=f'aw_fenestration_core module directory (default: {MODULE_DIR})')
    args = parser.parse_args()

    rebuild_melt(args.source, args.melted_out)
    profiles = load_profiles(args.melted_out)
    all_thickness_values = write_attributes_data(profiles, args.module_dir)
    write_profiles_data(profiles, args.module_dir)

    print('=== regeneration summary ===')
    print('templates written:', len(profiles))
    print('thickness attribute values:', len(all_thickness_values))
    print(all_thickness_values)
    print('finish attribute values:', len(FINISH_COLS))
    no_thickness_codes = [c for c, p in profiles.items() if not p['thicknesses']]
    print('codes with a Finish-only attribute line (no Thickness):', no_thickness_codes)
    zero_finish = [c for c, p in profiles.items() if not p['finishes']]
    print('codes with zero finish values (should be empty):', zero_finish)


if __name__ == '__main__':
    main()
