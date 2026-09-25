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
import os
import sys
from pathlib import Path

# The 169 M1 case is a real solve and takes about 9 seconds. Set
# AW_SKIP_SLOW_CHECKS=1 for a quick local commit -- but it prints a loud
# line when it does, and the full suite still has to run before a
# deploy. A check nobody notices being skipped is a check nobody has.
SKIP_SLOW = os.environ.get('AW_SKIP_SLOW_CHECKS') == '1'

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

    # ---- the 169 M1 job, DG-26 outer frames ----------------------------
    # Real data from the client's drawing: 31 windows, one each, outer
    # frame only, so four DG-26 pieces per window (2 x width,
    # 2 x height). The shop's settings: 3 mm kerf, no start trim, 25 mm
    # safety margin, everything mitred.
    #
    # Building the piece list is free; only the solves below are slow,
    # so the skip flag guards those rather than the data.
    windows = [
        (102, 99), (22, 99), (24, 48), (79, 229), (122, 22), (36, 24),
        (24, 53), (24, 48), (30, 45), (52, 90), (42, 22), (19, 55),
        (19, 48), (44, 84), (27, 46), (101, 83), (43, 90), (19, 116),
        (137, 115), (19, 115), (48, 85), (60, 83), (24, 46), (51, 84),
        (24, 48), (41, 84), (24, 48), (41, 84), (88, 92), (67, 18),
        (141, 28),
    ]
    if len(windows) != 31:
        fail('169 M1', 'expected 31 windows, have %s' % len(windows))

    frames = []
    for number, (width, height) in enumerate(windows, start=1):
        for _ in range(2):
            frames.append({'length': width * 25.4, 'angle': '45',
                           'label': 'W%02d width' % number})
        for _ in range(2):
            frames.append({'length': height * 25.4, 'angle': '45',
                           'label': 'W%02d height' % number})

    kerf, margin = 3.0, 25.0
    limit = cut.max_piece_mm(18 * FT, 0.0, margin, kerf, '45')
    # ~214.85 in at these settings.
    if not (214.0 < limit / 25.4 < 215.0):
        fail('169 M1', 'max piece is %.2f in, expected about 214.85'
             % (limit / 25.4))

    # ---- no option is ever worse than greedy ---------------------------
    # Column generation is seeded with the greedy packing's patterns, so
    # the integer solve always has that answer to fall back on. That is
    # what makes a time budget safe: running out decides "proven" versus
    # "within N ft", never a nonsense total. Before the seeding, an
    # 18 ft-only option cut short came back at 936 ft where greedy alone
    # manages 630.
    #
    # Deliberately run at SMALL budgets and always, skip flag or not:
    # short budgets are both the fast case and the one where falling
    # below greedy would actually happen.
    for budget in (2.0, 0.5):
        capped = cut.evaluate(frames, STOCK, kerf=kerf, start_trim=0.0,
                              safety_margin=margin, rate_per_ft=1.0,
                              time_budget=budget)
        for scenario in capped['scenarios']:
            if not scenario['feasible'] or not scenario['bar_count']:
                continue
            greedy = scenario.get('greedy_feet') or 0.0
            if not greedy:
                fail('greedy floor',
                     '%s reported no greedy total' % scenario['key'])
            elif scenario['feet_bought'] > greedy + 1e-6:
                fail('greedy floor',
                     'budget %ss: %s bought %.1f ft, worse than greedy at '
                     '%.1f ft' % (budget, scenario['key'],
                                  scenario['feet_bought'], greedy))

    if SKIP_SLOW:
        print('  !! AW_SKIP_SLOW_CHECKS=1 -- the full 169 M1 DG-26 solve '
              'was NOT run. Run the full suite before deploying.')
    else:
        result = cut.solve(frames, STOCK, kerf=kerf, start_trim=0.0,
                           safety_margin=margin, rate_per_ft=1.0)

        # 1. W04's two 229 in sides are refused; its 79 in pieces are not.
        oversize = sorted(round(p['length'] / 25.4)
                          for p in result['oversize'])
        if oversize != [229, 229]:
            fail('169 M1',
                 'refused %s, expected exactly the two 229 in sides'
                 % oversize)
        if result['placed_count'] != 122:
            fail('169 M1', 'placed %s pieces, expected 122'
                 % result['placed_count'])
        placed_79 = sum(
            1 for bar in result['bars'] for c in bar['cuts']
            if round(c['length'] / 25.4) == 79)
        if placed_79 != 2:
            fail('169 M1', "W04's two 79 in pieces were not nested")

        # 2. 599.33 ft of finished frame needs exactly 606 ft of bar, and
        #    that is provable: the LP bound is ~604.9 and every stock
        #    length is an even number of feet.
        finished = sum(c['length'] for bar in result['bars']
                       for c in bar['cuts']) / FT
        if abs(finished - 599.3333) > 0.01:
            fail('169 M1', 'finished frame is %.4f ft, expected 599.33'
                 % finished)
        if abs(result['feet_bought'] - 606.0) > 1e-6:
            fail('169 M1', 'bought %.4f ft, expected exactly 606'
                 % result['feet_bought'])
        if cut.HAS_SOLVER and not result['proven_optimal']:
            fail('169 M1', 'not reported as proven optimal (bound %.4f ft)'
                 % result['lower_bound_feet'])

        # 3. No bar is over-filled once saw loss and the margin count.
        for bar in result['bars']:
            consumed = sum(cut.piece_demand_mm(c['length'], kerf, '45')
                           for c in bar['cuts'])
            capacity = cut.usable_bar_mm(bar['stock_mm'], 0.0, margin)
            if consumed > capacity + 1e-6:
                fail('169 M1',
                     'a %.0f ft bar holds %.1f mm of cuts in %.1f mm'
                     % (bar['stock_mm'] / FT, consumed, capacity))

    # ---- the optimality claim must be sound ---------------------------
    # 14/16/18 ft bars share a gcd of 2, so nothing can total an odd
    # number of feet. A bound of 604.93 therefore means 606.
    if abs(cut.achievable_floor(604.9346, [14.0, 16.0, 18.0]) - 606.0) > 1e-9:
        fail('achievable floor', 'did not round 604.93 up to 606')
    if abs(cut.achievable_floor(606.0, [14.0, 16.0, 18.0]) - 606.0) > 1e-9:
        fail('achievable floor', 'moved a total that is already achievable')
    # Non-integer stock has no lattice to round to; leave it alone.
    if abs(cut.achievable_floor(100.5, [14.5, 16.0]) - 100.5) > 1e-9:
        fail('achievable floor', 'invented a lattice for fractional stock')

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
          'two provable optima, an FFD-beating case, %spiece conservation, '
          'bar capacity and infeasible options.'
          % ('exact solver' if cut.HAS_SOLVER else 'GREEDY FALLBACK - '
             'pulp not installed',
             'the greedy floor, ' if SKIP_SLOW else
             'the 169 M1 DG-26 job (606 ft, proven), the greedy floor, '))
    return 0


if __name__ == '__main__':
    sys.exit(main())
