# -*- coding: utf-8 -*-
"""Bar nesting for the cutting plan (spec 8, Phase 6c).

Ported from the HTML prototype's `nest()` / `packInto()`, with one
deliberate correction noted below. Kept free of Odoo imports, like
formula.py and profile_rate.resolve_chain, so
scripts/check_cut_plan.py exercises THIS code rather than a
reimplementation that would share none of its bugs.

Two rules the whole thing rests on:

- Kerf is charged for every piece, including the last on a bar. It
  slightly over-reserves, and that is the right direction to be wrong
  in: a plan that buys one bar too few stops the saw.
- A piece that does not fit is never dropped. The prototype's
  `if(!take.length){left.shift();continue;}` silently discards a piece
  too long for the bar length being evaluated, which is invisible in a
  yield table and shows up as a missing member on the shop floor. Here
  a single-length scenario that cannot hold a piece is marked
  INFEASIBLE instead, so it can still be shown and simply not chosen.
"""
MM_PER_FOOT = 304.8


def pack_bar(bar_mm, pieces, kerf):
    """Greedy first-fit down one bar over a descending-sorted list.

    Returns (taken, remaining_mm). `pieces` is not modified.
    """
    remaining = float(bar_mm)
    taken = []
    for piece in pieces:
        if piece['length'] + kerf <= remaining:
            taken.append(piece)
            remaining -= piece['length'] + kerf
    return taken, remaining


def _pack_all(pieces, kerf, pick_bar):
    """Fill bars until every piece is placed.

    `pick_bar(left)` returns (stock_mm, taken, remaining) or None when
    nothing fits, which means the scenario cannot hold what is left.
    """
    left = sorted(pieces, key=lambda p: -p['length'])
    bars = []
    while left:
        choice = pick_bar(left)
        if choice is None:
            return None, left          # infeasible, and this is why
        stock_mm, taken, remaining = choice
        bars.append({
            'stock_mm': stock_mm,
            'cuts': taken,
            'remainder': remaining,
        })
        placed = {id(piece) for piece in taken}
        left = [piece for piece in left if id(piece) not in placed]
    return bars, []


def _single_length(stock_mm):
    def pick(left):
        taken, remaining = pack_bar(stock_mm, left, pick.kerf)
        if not taken:
            return None
        return stock_mm, taken, remaining
    return pick


def _mixed(stock_list):
    def pick(left):
        best = None
        for stock_mm in stock_list:
            taken, remaining = pack_bar(stock_mm, left, pick.kerf)
            if not taken:
                continue
            # Remainder per piece placed: the prototype's score. It
            # prefers the bar that wastes least for what it holds,
            # rather than simply the longest bar.
            score = remaining / len(taken)
            if best is None or score < best[0]:
                best = (score, stock_mm, taken, remaining)
        if best is None:
            return None
        return best[1], best[2], best[3]
    return pick


def _summarise(bars, pieces, offcut_min, rate_per_ft):
    feet_bought = sum(bar['stock_mm'] for bar in bars) / MM_PER_FOOT
    used_mm = sum(piece['length'] for piece in pieces)
    feet_used = used_mm / MM_PER_FOOT
    bars_by_length = {}
    for bar in bars:
        bars_by_length[bar['stock_mm']] = \
            bars_by_length.get(bar['stock_mm'], 0) + 1
    return {
        'bars': bars,
        'bar_count': len(bars),
        'bars_by_length': bars_by_length,
        'feet_bought': feet_bought,
        'feet_used': feet_used,
        'waste_feet': feet_bought - feet_used,
        'yield_pct': (feet_used / feet_bought * 100.0) if feet_bought else 0.0,
        'cost': feet_bought * rate_per_ft,
        'offcuts': sorted(
            (bar['remainder'] for bar in bars
             if bar['remainder'] >= offcut_min), reverse=True),
    }


def evaluate(pieces, stock_mm_list, kerf=5.0, offcut_min=400.0,
             rate_per_ft=0.0):
    """Every scenario for one profile, plus which one wins.

    `pieces` is [{'length': mm, 'label': str, ...}, ...]; whatever else
    a piece carries is passed through untouched, so a cut stays
    traceable to the BOM line it came from.

    Returns scenarios in a stable order (each stock length, then
    Mixed), each with its own feasibility, so the estimator can pick a
    worse one on purpose -- "only 16 ft in the yard today" -- and see
    why a length is unavailable when it is.
    """
    stock_list = sorted(float(value) for value in stock_mm_list)
    if not stock_list:
        return {'scenarios': [], 'oversize': list(pieces),
                'chosen_key': None}
    longest = stock_list[-1]

    # Longer than the longest bar even before kerf: no scenario can
    # ever hold these, and they are the coupler-split cases.
    oversize = [p for p in pieces if p['length'] + kerf > longest]
    fitting = [p for p in pieces if p['length'] + kerf <= longest]

    scenarios = []
    for stock_mm in stock_list:
        picker = _single_length(stock_mm)
        picker.kerf = kerf
        bars, unplaced = _pack_all(fitting, kerf, picker)
        key = '%g' % round(stock_mm / MM_PER_FOOT, 4)
        entry = {
            'key': key,
            'label': '%s ft only' % key,
            'stock_mm': stock_mm,
            'feasible': bars is not None,
        }
        if bars is None:
            entry.update({
                'bars': [], 'bar_count': 0, 'bars_by_length': {},
                'feet_bought': 0.0, 'feet_used': 0.0, 'waste_feet': 0.0,
                'yield_pct': 0.0, 'cost': 0.0, 'offcuts': [],
                'blocked_by': sorted(
                    (p['length'] for p in unplaced), reverse=True)[:3],
            })
        else:
            entry.update(
                _summarise(bars, fitting, offcut_min, rate_per_ft))
        scenarios.append(entry)

    picker = _mixed(stock_list)
    picker.kerf = kerf
    bars, _unplaced = _pack_all(fitting, kerf, picker)
    mixed = {'key': 'mixed', 'label': 'Mixed', 'stock_mm': 0.0,
             'feasible': bars is not None}
    # Mixed can always place anything that fits the longest bar, so it
    # is the guaranteed-feasible fallback.
    mixed.update(_summarise(bars or [], fitting, offcut_min, rate_per_ft))
    scenarios.append(mixed)

    usable = [s for s in scenarios if s['feasible'] and s['bar_count']]
    chosen = None
    if usable:
        # Cheapest, with bar-feet as the tie-break and the declared
        # order after that, so the result is deterministic rather than
        # depending on dict ordering.
        chosen = min(usable, key=lambda s: (
            round(s['cost'], 6), round(s['feet_bought'], 6),
            scenarios.index(s)))
    return {
        'scenarios': scenarios,
        'oversize': oversize,
        'chosen_key': chosen['key'] if chosen else None,
    }


def scenario_by_key(result, key):
    """The scenario an override names, or the chosen one."""
    for scenario in result['scenarios']:
        if scenario['key'] == key and scenario['feasible']:
            return scenario
    for scenario in result['scenarios']:
        if scenario['key'] == result['chosen_key']:
            return scenario
    return None
