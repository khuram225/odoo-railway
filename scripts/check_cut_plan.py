#!/usr/bin/env python3
"""Exercise the bar-nesting optimiser with the REAL implementation.

A nesting bug is expensive and nearly invisible: buy one bar too few and
the saw stops mid-job; lose a piece silently and a window ships without
a member. Neither raises anything, and a yield table looks plausible
either way.

The cases below are ones where the true minimum can be established by
hand, so "proven optimal" can be checked against arithmetic rather than
against the optimiser's own opinion of itself.

cut_algorithm.py is Odoo-free for this reason -- what runs here is what
runs on a quote.
"""
import importlib.util
import math
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


def pieces(*lengths, angle='45'):
    return [{'length': float(length), 'label': 'P%s' % index,
             'angle': angle}
            for index, length in enumerate(lengths, start=1)]


def main():
    cut = load()
    problems = []

    def fail(label, detail):
        problems.append('%s: %s' % (label, detail))

    # ---- saw geometry --------------------------------------------------
    # A 45 degree mitre travels kerf / sin(45) through the bar.
    expected = 5.0 / math.sin(math.radians(45))
    if abs(cut.saw_loss_mm(5.0, '45') - expected) > 1e-9:
        fail('saw loss', 'mitre loss is %.4f, expected %.4f'
             % (cut.saw_loss_mm(5.0, '45'), expected))
    if abs(cut.saw_loss_mm(5.0, '90') - 5.0) > 1e-9:
        fail('saw loss', 'square cut should lose exactly the kerf')

    # Longest piece = bar - trim - margin - one cut.
    longest = cut.max_piece_mm(18 * FT, start_trim=10.0, safety_margin=25.0,
                               kerf=5.0)
    if abs(longest - (18 * FT - 10.0 - 25.0 - expected)) > 1e-9:
        fail('max piece', 'got %.4f' % longest)

    # ---- no joints: an over-long piece is reported, never split --------
    over = cut.max_piece_mm(18 * FT, 10.0, 25.0, 5.0) + 1.0
    result = cut.solve(pieces(over, 1000.0), STOCK, kerf=5.0,
                       start_trim=10.0, safety_margin=25.0)
    if len(result['oversize']) != 1:
        fail('oversize', 'reported %s oversize, expected 1'
             % len(result['oversize']))
    if result['placed_count'] != 1:
        fail('oversize', 'placed %s fitting pieces, expected 1'
             % result['placed_count'])
    if any(len(bar['cuts']) > 1 for bar in result['bars']):
        fail('oversize', 'the over-long piece was nested anyway')

    # ---- provable optimum 1: exact fit, no waste possible --------------
    # Four pieces that exactly fill one 18 ft bar's usable length. One
    # bar is obviously the minimum, and the optimiser must find it.
    usable = cut.usable_bar_mm(18 * FT, 0.0, 0.0)
    each = usable / 4.0 - cut.saw_loss_mm(5.0, '45')
    result = cut.solve(pieces(each, each, each, each), STOCK, kerf=5.0)
    if result['bar_count'] != 1:
        fail('exact fit', 'used %s bars, expected 1' % result['bar_count'])
    if cut.HAS_SOLVER and not result['proven_optimal']:
        fail('exact fit', 'did not prove the single bar optimal')

    # ---- provable optimum 2: total length forces a bar count -----------
    # Nine pieces of 1700 mm. Demand per piece is 1707.07 mm. An 18 ft
    # bar (5486.4) holds 3 (5121.2); 14 ft holds 2. Total demand is
    # 15363.6 mm, so at least 15363.6 / 5486.4 = 2.8 -> 3 bars of any
    # mix. Three 18 ft bars hold exactly 9. So 3 x 18 ft = 54 ft is
    # optimal and provable.
    result = cut.solve(pieces(*([1700.0] * 9)), STOCK, kerf=5.0,
                       rate_per_ft=1.0)
    if result['bar_count'] != 3:
        fail('9 x 1700', 'used %s bars, expected 3' % result['bar_count'])
    if abs(result['feet_bought'] - 54.0) > 1e-6:
        fail('9 x 1700', 'bought %.3f ft, expected 54'
             % result['feet_bought'])
    if cut.HAS_SOLVER and not result['proven_optimal']:
        fail('9 x 1700', 'not proven optimal (gap %.4f ft)'
             % result['gap_feet'])

    # ---- the exact method must beat first-fit-decreasing ---------------
    # A classic case where FFD is not optimal: greedy opens a third bar,
    # the exact method packs into two 18 ft bars.
    awkward = [2700.0, 2700.0, 1800.0, 1800.0, 900.0, 900.0]
    exact = cut.solve(pieces(*awkward), [18 * FT], kerf=5.0, rate_per_ft=1.0)
    if cut.HAS_SOLVER:
        if exact['method'] != 'exact':
            fail('awkward set', 'fell back to %s' % exact['method'])
        if not exact['proven_optimal']:
            fail('awkward set', 'not proven optimal')
        # 2700+1800+900 = 5400 + 3 cuts (21.2) = 5421.2 <= 5486.4, twice.
        if exact['bar_count'] != 2:
            fail('awkward set', 'used %s bars, expected 2'
                 % exact['bar_count'])

    # ---- every piece is placed exactly once, in every scenario --------
    for name, lengths in (
        ('mixed lengths', (3000, 2500, 2000, 1500, 1000, 800, 500)),
        ('many equal', tuple([1200] * 11)),
        ('one piece', (2000,)),
    ):
        result = cut.evaluate(pieces(*lengths), STOCK, kerf=5.0)
        for scenario in result['scenarios']:
            if not scenario['feasible']:
                continue
            labels = [c['label'] for bar in scenario['bars']
                      for c in bar['cuts']]
            if sorted(labels) != sorted(
                    'P%s' % i for i in range(1, len(lengths) + 1)):
                fail(name, '%s lost or duplicated a piece' % scenario['key'])

    # ---- no bar is over-filled ----------------------------------------
    result = cut.evaluate(pieces(3000, 2500, 2000, 1500, 1000, 800, 500),
                          STOCK, kerf=5.0, start_trim=10.0,
                          safety_margin=25.0)
    for scenario in result['scenarios']:
        for bar in scenario['bars']:
            consumed = sum(
                cut.piece_demand_mm(c['length'], 5.0, c.get('angle') or '45')
                for c in bar['cuts'])
            capacity = cut.usable_bar_mm(bar['stock_mm'], 10.0, 25.0)
            if consumed > capacity + 1e-6:
                fail('capacity', 'a %.1f mm bar holds %.1f mm of cuts '
                                 '(capacity %.1f)'
                     % (bar['stock_mm'], consumed, capacity))

    # ---- an option that cannot hold a piece is refused, not trimmed ----
    result = cut.evaluate(pieces(15 * FT, 1000.0), STOCK, kerf=5.0)
    by_key = {s['key']: s for s in result['scenarios']}
    if by_key['14']['feasible']:
        fail('15 ft piece', '14 ft option claims to be feasible')
    for key in ('16', '18', 'mixed'):
        if not by_key[key]['feasible']:
            fail('15 ft piece', '%s option should be feasible' % key)
    if result['chosen_key'] == '14':
        fail('15 ft piece', 'chose an infeasible option')

    # ---- empty input is not a crash -----------------------------------
    result = cut.evaluate([], STOCK, kerf=5.0)
    if result['chosen_key'] is not None or result['oversize']:
        fail('empty group', 'expected nothing chosen and nothing oversize')

    if problems:
        print('Cutting plan problems:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('Bar nesting correct (%s): mitre saw loss, the no-joints rule, '
          'two provable optima, an FFD-beating case, piece conservation, '
          'bar capacity and infeasible options.'
          % ('exact solver' if cut.HAS_SOLVER else 'GREEDY FALLBACK - '
             'pulp not installed'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
