#!/usr/bin/env python3
"""Validate every seeded formula with the real grammar, and check the
engine's piece arithmetic against a worked example.

The formula module is deliberately free of Odoo imports so this can run
it directly — the same reason layout_rules.py is. A formula that only
fails when the explosion engine reaches it would surface as a wrong
length on a quote, which is the worst possible place to find out.
"""
import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / 'odoo' / 'addons' / 'aw_fenestration_core'
DESIGN = ROOT / 'odoo' / 'addons' / 'aw_fenestration_design'
MM_FT = 304.8

BOM_DEFAULTS_RE = re.compile(r'BOM_DEFAULTS = \{.*\n\}', re.S)
SERIES_DEFAULT_RE = re.compile(
    r"(glass_\w+|mesh_[wh])\s*=\s*fields\.Char\([^)]*default='([^']*)'")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_seed_xmlids(position_source):
    """Every xmlid a seed dict names must actually be seeded.

    Both BOM_DEFAULTS and OPTIONAL_POSITIONS look records up with
    raise_if_not_found=False, which is right at runtime -- an upgrade
    should not die over it -- but means a typo does nothing at all,
    silently, and the position keeps whatever it had. Here is the place
    to be strict about it.
    """
    seeded = set(re.findall(
        r'<record id="(pos_\w+)" model="aw\.profile\.position"',
        (CORE / 'data' / 'dynamic_seed_data.xml').read_text(
            encoding='utf-8')))
    problems = []
    for name in ('BOM_DEFAULTS', 'OPTIONAL_POSITIONS'):
        match = re.search(
            r'^%s = [\{\(].*?^[\}\)]' % name, position_source,
            re.S | re.M)
        if not match:
            problems.append('%s not found in profile_position.py' % name)
            continue
        referenced = set(re.findall(r"'(pos_\w+)'", match.group(0)))
        for xmlid in sorted(referenced - seeded):
            problems.append(
                '%s names %r, which dynamic_seed_data.xml never creates'
                % (name, xmlid))
    return problems


def check_scope_labels(position_source):
    """Every scope needs a phrase for the "missing line" warning.

    Without one the check falls back to the raw scope name, so the user
    is told their section is missing a 'junction_interlock' rather than
    an interlock junction. Cheap to get wrong when a scope is added.
    """
    match = re.search(r'scope = fields\.Selection\(\[(.*?)\]',
                      position_source, re.S)
    if not match:
        return ['scope Selection not found in profile_position.py']
    scopes = set(re.findall(r"\('(\w+)',", match.group(1)))

    explosion = (DESIGN / 'models' / 'explosion.py').read_text(
        encoding='utf-8')
    label_match = re.search(r'SCOPE_DEMAND_LABEL = \{(.*?)^\}', explosion,
                            re.S | re.M)
    if not label_match:
        return ['SCOPE_DEMAND_LABEL not found in explosion.py']
    labelled = set(re.findall(r"^\s*'(\w+)':", label_match.group(1), re.M))

    return ['scope %r has no SCOPE_DEMAND_LABEL entry' % s
            for s in sorted(scopes - labelled)]


def main():
    formula = load('formula', CORE / 'models' / 'formula.py')

    source = (CORE / 'models' / 'profile_position.py').read_text(
        encoding='utf-8')
    match = BOM_DEFAULTS_RE.search(source)
    if not match:
        print('BOM_DEFAULTS not found in profile_position.py')
        return 1
    defaults = ast.literal_eval(match.group(0).split('=', 1)[1].strip())

    problems = []
    for xmlid, values in defaults.items():
        for key in ('default_length', 'default_length_h', 'default_qty'):
            error = formula.validate_formula(values.get(key))
            if error:
                problems.append(f'{xmlid}.{key}: {error}')

    series = (CORE / 'models' / 'window_series.py').read_text(encoding='utf-8')
    series_defaults = 0
    for found in SERIES_DEFAULT_RE.finditer(series):
        series_defaults += 1
        error = formula.validate_formula(found.group(2))
        if error:
            problems.append(f'aw.window.series.{found.group(1)}: {error}')

    # The grammar must keep rejecting what it is meant to reject: a
    # validator that has quietly become permissive is worse than none,
    # because everything still looks checked.
    for bad in ('__import__("os")', 'PW.real', 'lambda: 1', '[1]',
                'sqrt(PW)', 'XX'):
        if formula.validate_formula(bad) is None:
            problems.append(f'grammar accepts {bad!r}, which it must not')

    # Worked example: 8ft x 5ft with two sliders, matching the spec's own
    # P4 test, so the numbers here can be checked by hand.
    width, height = 8 * MM_FT, 5 * MM_FT
    context = {
        'W': width, 'H': height, 'PW': width / 2, 'PH': height,
        'CW': width, 'CH': height, 'N': 2, 'T': 2,
    }
    expected = [
        ('W', width),
        ('H', height),
        ('PW - 10', width / 2 - 10),
        ('PH - 10', height - 10),
        ('PW - 80', width / 2 - 80),
        ('PH - 80', height - 80),
    ]
    for expression, want in expected:
        got = formula.evaluate_formula(expression, context)
        if abs(got - want) > 1e-6:
            problems.append(f'{expression} gave {got}, expected {want}')

    problems.extend(check_seed_xmlids(source))
    problems.extend(check_scope_labels(source))

    if problems:
        print('Formula problems:')
        for problem in problems:
            print(f'  {problem}')
        return 1

    print(f'{len(defaults)} seeded position rule(s) and {series_defaults} '
          f'Series deduction(s) are valid; the grammar still rejects what '
          f'it should.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
