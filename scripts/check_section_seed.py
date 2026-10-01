#!/usr/bin/env python3
"""Every profile a Profile Section seeds must be sold in a thickness
the seed can actually pick.

The failure this exists for is silent at every layer. Thickness is a
Dynamic-creation attribute, so a variant only comes into existence when
a combination is REQUESTED -- and a combination naming a value the
template does not carry makes no variant at all, with no error. The
seeded "Double Glaze - Openable" section asked all six RE- profiles for
'Normal'; the Chawla price list sells every one of them only in 'Std'.
The result was "No product" on every profile line, no rate, no cost,
and a design that priced at zero.

Nothing else could see it: the seed data is valid XML, the section
records create fine, the lines have a thickness, and the mismatch only
exists ACROSS two data files -- the seed's preference in
`section_seed.py` and the attribute lines in `chawla_profiles_data.xml`.

This reads both and runs the REAL decision -- `choose_thickness` out of
`models/thickness.py`, which is kept free of Odoo imports for exactly
this reason, the same way `layout_rules.py` and `resolve_chain` are.
Reimplementing the rule here would produce a check that agrees with
itself for ever, and the rule disagreeing with the data is the whole
bug: the original seed simply stored the preferred value, and this
check fails on all six RE- profiles if it is put back.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / 'odoo' / 'addons' / 'aw_fenestration_core'
ATTRIBUTES = CORE / 'data' / 'chawla_attributes_data.xml'
PROFILES = CORE / 'data' / 'chawla_profiles_data.xml'

sys.path.insert(0, str(CORE / 'models'))
from thickness import choose_thickness  # noqa: E402

# The seed's preferred thickness, as the module names it. Read from
# section_seed.py rather than hardcoded, so changing it there is
# checked here instead of quietly diverging.
PREFERRED_XMLID_RE = re.compile(
    r"aw_fenestration_core\.(aw_attr_val_thickness_\w+)")


def thickness_value_names():
    """xmlid -> name, for every Thickness attribute value."""
    root = ET.parse(ATTRIBUTES).getroot()
    names = {}
    for record in root.iter('record'):
        rid = record.get('id') or ''
        if not rid.startswith('aw_attr_val_thickness_'):
            continue
        field = record.find("field[@name='name']")
        names[rid] = (field.text or '').strip() if field is not None else ''
    return names


def template_thicknesses(names):
    """product name -> sorted list of thickness value names it offers.

    The attribute lines are written inline on the template record as an
    `eval` of (0, 0, {...}) commands, which is how the generator emits
    them -- parsed with a regex rather than eval'd, since running
    arbitrary data-file expressions to check a data file is a worse
    trade than a brittle-looking pattern over output we generate.
    """
    root = ET.parse(PROFILES).getroot()
    offered = {}
    for record in root.iter('record'):
        if record.get('model') != 'product.template':
            continue
        name_field = record.find("field[@name='name']")
        if name_field is None:
            continue
        name = (name_field.text or '').strip()
        lines = record.find("field[@name='attribute_line_ids']")
        block = re.search(
            r"ref\('aw_attribute_thickness'\), 'value_ids': "
            r"\[\(6, 0, \[([^\]]*)\]\)\]",
            (lines.get('eval') or '') if lines is not None else '')
        ids = re.findall(r"ref\('([^']+)'\)", block.group(1)) if block else []
        offered[name] = sorted(names.get(i, i) for i in ids)
    return offered


def seeded_products():
    """(preferred thickness name, {code, ...}) from section_seed.py.

    Every profile the seed names, DEFAULTS AND ALTERNATES ALIKE. An
    alternate matters as much as a default here: the divider resolves it
    with the LINE's thickness, so an alternate the product is not sold
    in makes no variant and the divider silently cuts nothing -- exactly
    the failure this check exists for, one layer along.
    """
    source = (CORE / 'models' / 'section_seed.py').read_text(encoding='utf-8')
    match = PREFERRED_XMLID_RE.search(source)
    preferred = thickness_value_names().get(match.group(1), '') if match else ''
    block = re.search(r'SECTION_LINES = \{(.*?)\n\}', source, re.S)
    if not block:
        return preferred, set()
    # ('RE-1', ['RE-3']): the default is the first quoted string of the
    # tuple, the alternates are the quoted strings in the list.
    codes = set()
    pattern = r"\(\s*'([^']+)'\s*,\s*\[([^\]]*)\]\s*\)"
    for default, alternates in re.findall(pattern, block.group(1)):
        codes.add(default)
        codes.update(re.findall(r"'([^']+)'", alternates))
    return preferred, codes


def main():
    if not (ATTRIBUTES.is_file() and PROFILES.is_file()):
        print('check_section_seed: Chawla data files not found, skipping')
        return 0

    names = thickness_value_names()
    offered = template_thicknesses(names)
    preferred, codes = seeded_products()
    if not codes:
        print('check_section_seed: no seeded section lines found')
        return 1

    problems, resolved = [], []
    for code in sorted(codes):
        # Same fallback the seed uses: exact name, then the price
        # list's 'M.F' spelling.
        available = None
        for candidate in (code, '%s M.F' % code):
            if candidate in offered:
                available = offered[candidate]
                break
        if available is None:
            problems.append(
                '%s is seeded into a Profile Section but is not in the '
                'price list at all' % code)
            continue
        chosen, problem = choose_thickness(preferred, available)
        if problem:
            problems.append('%s %s' % (code, problem))
        elif chosen not in available:
            # The rule returned something the product is not sold in
            # and did not call it a problem -- no variant, no error,
            # no cost. This is the shape of the original bug.
            problems.append(
                "%s would be seeded with '%s', which it is not sold in "
                "(available: %s)" % (code, chosen, ', '.join(available)))
        else:
            resolved.append('%s -> %s' % (code, chosen))

    if problems:
        print('Seeded profiles whose thickness cannot resolve to a variant:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('%s seeded profile(s) resolve to a thickness they are sold in: %s'
          % (len(resolved), '; '.join(resolved)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
