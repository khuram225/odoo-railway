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
MM_FT = 304.8

BOM_DEFAULTS_RE = re.compile(r'BOM_DEFAULTS = \{.*\n\}', re.S)
SERIES_DEFAULT_RE = re.compile(
    r"(glass_\w+|mesh_[wh])\s*=\s*fields\.Char\([^)]*default='([^']*)'")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
