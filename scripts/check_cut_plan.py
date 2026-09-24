#!/usr/bin/env python3
"""Exercise the bar-nesting algorithm with the REAL implementation.

A nesting bug is expensive and almost invisible: buy one bar too few
and the saw stops mid-job; lose a piece silently and a window ships
without a member. Neither raises anything, and a yield table looks
perfectly plausible either way.

cut_algorithm.py is kept free of Odoo imports for exactly this reason,
so what runs here is what runs on the quote.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = (ROOT / 'odoo' / 'addons' / 'aw_fenestration_design' / 'models'
          / 'cut_algorithm.py')

FT = 304.8
STOCK = [14 * FT, 16 * FT, 18 * FT]


def load():
    spec = importlib.util.spec_from_file_location('cut_algorithm', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pieces(*lengths):
    return [{'length': float(length), 'label': 'P%s' % index}
            for index, length in enumerate(lengths, start=1)]


def main():
    cut = load()
    problems = []

    def fail(label, detail):
        problems.append('%s: %s' % (label, detail))

    # ---- the spec's worked example -------------------------------------
    # Three pieces of 76.33 in (1938.78 mm). Two fit a 14 ft bar
    # (2 x 1943.78 = 3887.56 <= 4267.2); three do not fit ANY stock
    # length (3 x 1943.78 = 5831.34 > 5486.4). So every option needs two
    # bars, and the cheapest is the one that buys the least: 2 x 14 ft.
    length = 76.33 * 25.4
    result = cut.evaluate(pieces(length, length, length), STOCK,
                          kerf=5.0, offcut_min=400.0, rate_per_ft=1.0)
    chosen = cut.scenario_by_key(result, result['chosen_key'])
    if result['chosen_key'] != '14':
        fail('3 x 76.33in', 'chose %r, expected the 14 ft option'
             % result['chosen_key'])
    if chosen['bar_count'] != 2:
        fail('3 x 76.33in', 'used %s bars, expected 2' % chosen['bar_count'])
    if abs(chosen['feet_bought'] - 28.0) > 1e-6:
        fail('3 x 76.33in', 'bought %.4f ft, expected 28'
             % chosen['feet_bought'])
    placed = sum(len(bar['cuts']) for bar in chosen['bars'])
    if placed != 3:
        fail('3 x 76.33in', 'placed %s pieces, expected 3' % placed)
    # No single bar can take all three -- the point of the example.
    if any(len(bar['cuts']) == 3 for bar in chosen['bars']):
        fail('3 x 76.33in', 'put all three on one bar, which does not fit')
    # 4267.2 - 2*1943.78 = 379.64, below the 400 minimum; the second
    # bar's remainder is well above it.
    if len(chosen['offcuts']) != 1:
        fail('3 x 76.33in', 'offcuts %s, expected exactly one above 400mm'
             % chosen['offcuts'])

    # ---- a piece longer than the longest bar ---------------------------
    over = 19 * FT
    result = cut.evaluate(pieces(over, 1000.0), STOCK, kerf=5.0)
    if len(result['oversize']) != 1:
        fail('oversize piece', 'reported %s oversize, expected 1'
             % len(result['oversize']))
    if result['oversize'] and result['oversize'][0]['length'] != over:
        fail('oversize piece', 'reported the wrong piece')
    chosen = cut.scenario_by_key(result, result['chosen_key'])
    placed = sum(len(bar['cuts']) for bar in chosen['bars'])
    if placed != 1:
        fail('oversize piece',
             'placed %s of the fitting pieces, expected 1' % placed)

    # ---- nothing is ever silently dropped ------------------------------
    # 15 ft does not fit a 14 ft bar, so the 14-only option is
    # impossible -- it must say so, NOT quietly leave the piece out.
    result = cut.evaluate(pieces(15 * FT, 1000.0), STOCK, kerf=5.0)
    by_key = {s['key']: s for s in result['scenarios']}
    if by_key['14']['feasible']:
        fail('15 ft piece', '14 ft option claims to be feasible')
    for key in ('16', '18', 'mixed'):
        if not by_key[key]['feasible']:
            fail('15 ft piece', '%s option should be feasible' % key)
    if result['chosen_key'] == '14':
        fail('15 ft piece', 'chose an infeasible option')

    # Every fitting piece appears exactly once in every feasible option.
    for name, lengths in (
        ('mixed lengths', (3000, 2500, 2000, 1500, 1000, 800, 500)),
        ('many equal', tuple([1200] * 11)),
        ('one piece', (2000,)),
    ):
        result = cut.evaluate(pieces(*lengths), STOCK, kerf=5.0)
        for scenario in result['scenarios']:
            if not scenario['feasible']:
                continue
            labels = [cutrow['label'] for bar in scenario['bars']
                      for cutrow in bar['cuts']]
            if sorted(labels) != sorted(
                    'P%s' % i for i in range(1, len(lengths) + 1)):
                fail(name, '%s lost or duplicated a piece: %s'
                     % (scenario['key'], labels))

    # ---- no bar is over-filled ----------------------------------------
    result = cut.evaluate(pieces(3000, 2500, 2000, 1500, 1000, 800, 500),
                          STOCK, kerf=5.0)
    for scenario in result['scenarios']:
        for bar in scenario['bars']:
            consumed = sum(c['length'] + 5.0 for c in bar['cuts'])
            if consumed > bar['stock_mm'] + 1e-9:
                fail('capacity', 'a %s mm bar holds %.1f mm of cuts'
                     % (bar['stock_mm'], consumed))
            if abs((bar['stock_mm'] - consumed) - bar['remainder']) > 1e-6:
                fail('capacity', 'remainder does not match what was cut')

    # ---- an empty group is not a crash --------------------------------
    result = cut.evaluate([], STOCK, kerf=5.0)
    if result['chosen_key'] is not None or result['oversize']:
        fail('empty group', 'expected nothing chosen and nothing oversize')

    if problems:
        print('Cutting plan problems:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('Bar nesting correct: the 3 x 76.33 in example, an oversize '
          'piece, an infeasible bar length, piece conservation and bar '
          'capacity.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
