# -*- coding: utf-8 -*-
"""Exact bar nesting for the cutting plan (spec 8, Phase 6c).

**No joints, no couplers.** Every piece must come out of one bar. A
piece that cannot is a hard error on the design, never something the
optimiser works around by splitting it.

The method is pattern-based column generation, not a greedy pack:

1. Start from trivial patterns (one item type repeated down a bar).
2. Solve the LP relaxation over the patterns so far -- how many of each
   pattern to run, allowing fractions.
3. Price: for each stock length, solve a bounded knapsack using the LP
   duals as item values. A pattern worth more than the bar costs is an
   improving column; add it and go round again.
4. When nothing prices in, the LP objective is a true LOWER BOUND on
   bar-feet. Solve the integer problem over the collected patterns for
   the answer actually cut.
5. Integer cost equal to that bound means provably optimal; otherwise
   the gap is reported honestly rather than implied.

Odoo-free on purpose, like formula.py and resolve_chain, so
scripts/check_cut_plan.py exercises exactly what runs on a quote.
The LP/MIP goes through pulp when it is installed; without it the
module falls back to first-fit-decreasing and says so, because a plan
that silently stops being optimal is worse than one that admits it.
"""
import math
from collections import defaultdict

MM_PER_FOOT = 304.8

try:                                            # pragma: no cover
    import pulp
    HAS_SOLVER = True
except ImportError:                             # pragma: no cover
    pulp = None
    HAS_SOLVER = False


# ----------------------------------------------------------------------
# saw geometry
# ----------------------------------------------------------------------
def saw_loss_mm(kerf, angle='45'):
    """Material lost to one cut.

    A mitre does not cut straight across: at 45 degrees the blade
    travels kerf / sin(45) through the bar, about 1.41x the kerf. Using
    the plain kerf for mitred pieces under-reserves on every single cut,
    which compounds down a bar and eventually costs a piece.
    """
    if str(angle) == '45':
        return kerf / math.sin(math.radians(45))
    return float(kerf)


def usable_bar_mm(bar_mm, start_trim=0.0, safety_margin=0.0):
    """What is actually available on a bar once the end is squared off
    and the safety margin is held back."""
    return max(0.0, float(bar_mm) - float(start_trim) - float(safety_margin))


def max_piece_mm(longest_bar_mm, start_trim=0.0, safety_margin=0.0,
                 kerf=5.0, angle='45'):
    """The longest piece that can be cut at all.

    One saw cut is subtracted because even a single piece taken off a
    bar costs one. Quoted at 45 degrees by default: it is the larger
    loss, so the figure shown to the user is the safe one rather than
    one that holds only for square cuts.
    """
    return usable_bar_mm(longest_bar_mm, start_trim, safety_margin) \
        - saw_loss_mm(kerf, angle)


def piece_demand_mm(length, kerf, angle='45'):
    """What one piece consumes off a bar: itself plus its cut."""
    return float(length) + saw_loss_mm(kerf, angle)


# ----------------------------------------------------------------------
# bounded knapsack, used for pricing
# ----------------------------------------------------------------------
def _bounded_knapsack(capacity, weights, values, counts):
    """Maximise value within capacity, at most `counts[i]` of item i.

    Integer capacity in mm. Bounded counts are handled by binary
    splitting, which keeps this O(capacity * sum(log count)) rather
    than the naive O(capacity * sum(count)).
    """
    capacity = int(capacity)
    if capacity <= 0:
        return 0.0, [0] * len(weights)

    best = [0.0] * (capacity + 1)
    # choice[c] = (item_index, bundle_size) taken to reach c
    choice = [None] * (capacity + 1)

    for index, (weight, value, count) in enumerate(
            zip(weights, values, counts)):
        if weight <= 0 or weight > capacity or count <= 0:
            continue
        bundle = 1
        remaining = count
        while remaining > 0:
            take = min(bundle, remaining)
            bundle_weight = weight * take
            bundle_value = value * take
            if bundle_weight <= capacity:
                for cap in range(capacity, bundle_weight - 1, -1):
                    candidate = best[cap - bundle_weight] + bundle_value
                    if candidate > best[cap] + 1e-12:
                        best[cap] = candidate
                        choice[cap] = (index, take, cap - bundle_weight)
            remaining -= take
            bundle *= 2

    # Walk the best cell back to a pattern.
    top = max(range(capacity + 1), key=lambda c: best[c])
    pattern = [0] * len(weights)
    cap = top
    while choice[cap] is not None:
        index, take, previous = choice[cap]
        pattern[index] += take
        cap = previous
    # Binary splitting can exceed the bound when two bundles of the same
    # item combine; clamp rather than emit an impossible pattern.
    for index, count in enumerate(counts):
        pattern[index] = min(pattern[index], count)
    return best[top], pattern


# ----------------------------------------------------------------------
# the solve
# ----------------------------------------------------------------------
def _trivial_patterns(demand_mm, counts, capacities):
    """One pattern per (stock length, item): that item repeated."""
    patterns = []
    for stock_index, capacity in enumerate(capacities):
        for item_index, weight in enumerate(demand_mm):
            if weight <= 0 or weight > capacity:
                continue
            fit = min(int(capacity // weight), counts[item_index])
            if fit <= 0:
                continue
            row = [0] * len(demand_mm)
            row[item_index] = fit
            patterns.append((stock_index, tuple(row)))
    return patterns


def _solve_lp(patterns, counts, costs, integer=False):
    """min sum(cost * x) s.t. pattern coverage >= counts.

    Returns (objective, x values, duals). Duals are None for the integer
    solve, which has none.
    """
    problem = pulp.LpProblem('cutting', pulp.LpMinimize)
    category = 'Integer' if integer else 'Continuous'
    variables = [
        pulp.LpVariable('x%s' % index, lowBound=0, cat=category)
        for index in range(len(patterns))
    ]
    problem += pulp.lpSum(
        costs[stock_index] * variables[index]
        for index, (stock_index, _row) in enumerate(patterns))

    constraints = []
    for item_index, need in enumerate(counts):
        constraint = pulp.lpSum(
            row[item_index] * variables[index]
            for index, (_stock, row) in enumerate(patterns)
            if row[item_index]
        ) >= need
        problem += constraint
        constraints.append(problem.constraints[list(
            problem.constraints.keys())[-1]])

    status = problem.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[status] != 'Optimal':
        return None, None, None
    values = [v.value() or 0.0 for v in variables]
    duals = None
    if not integer:
        duals = [max(0.0, constraint.pi or 0.0)
                 for constraint in constraints]
    return pulp.value(problem.objective), values, duals


def _column_generation(demand_mm, counts, capacities, costs,
                       max_rounds=60):
    """Grow the pattern set until no bar prices in."""
    patterns = _trivial_patterns(demand_mm, counts, capacities)
    if not patterns:
        return None, None, None
    seen = {(stock, row) for stock, row in patterns}

    bound = None
    for _round in range(max_rounds):
        objective, _values, duals = _solve_lp(patterns, counts, costs)
        if objective is None:
            return None, None, None
        bound = objective
        added = False
        for stock_index, capacity in enumerate(capacities):
            value, pattern = _bounded_knapsack(
                capacity,
                [int(math.ceil(w)) for w in demand_mm],
                duals, counts)
            # Worth more in dual value than the bar costs: an improving
            # column. The tolerance keeps it from cycling on noise.
            if value > costs[stock_index] + 1e-6:
                key = (stock_index, tuple(pattern))
                if key not in seen and any(pattern):
                    seen.add(key)
                    patterns.append(key)
                    added = True
        if not added:
            break

    return patterns, bound, True


def _greedy(demand_mm, counts, capacities, costs):
    """First-fit-decreasing fallback, used when pulp is absent.

    Deliberately kept simple: its job is to produce a workable plan and
    be honest that it is not proven optimal, not to compete.
    """
    items = []
    for index, count in enumerate(counts):
        items.extend([index] * count)
    items.sort(key=lambda i: -demand_mm[i])

    bars = []
    for item in items:
        placed = False
        for bar in bars:
            if demand_mm[item] <= bar['left'] + 1e-9:
                bar['row'][item] += 1
                bar['left'] -= demand_mm[item]
                placed = True
                break
        if placed:
            continue
        # Cheapest bar that can take it.
        options = [i for i, cap in enumerate(capacities)
                   if demand_mm[item] <= cap + 1e-9]
        if not options:
            return None
        stock_index = min(options, key=lambda i: costs[i])
        row = defaultdict(int)
        row[item] = 1
        bars.append({'stock': stock_index, 'row': row,
                     'left': capacities[stock_index] - demand_mm[item]})
    return [(bar['stock'], tuple(bar['row'].get(i, 0)
                                 for i in range(len(counts))))
            for bar in bars]


def solve(pieces, stock_mm_list, kerf=5.0, start_trim=0.0,
          safety_margin=0.0, offcut_min=400.0, rate_per_ft=0.0):
    """Nest one profile group. Returns bars plus how good the answer is.

    Pieces too long for the longest bar are returned in `oversize` and
    are NOT nested: with no joints allowed there is nothing to do with
    them but report them.
    """
    stock_list = sorted(float(v) for v in stock_mm_list)
    result = {
        'bars': [], 'oversize': [], 'feasible': True,
        'method': 'none', 'proven_optimal': False, 'gap_feet': 0.0,
        'lower_bound_feet': 0.0,
    }
    if not stock_list or not pieces:
        result['oversize'] = list(pieces) if not stock_list else []
        return _summarise(result, pieces, offcut_min, rate_per_ft)

    capacities = [usable_bar_mm(v, start_trim, safety_margin)
                  for v in stock_list]
    longest = max(capacities)

    fitting, oversize = [], []
    for piece in pieces:
        need = piece_demand_mm(
            piece['length'], kerf, piece.get('angle') or '45')
        if need > longest + 1e-9:
            oversize.append(piece)
        else:
            fitting.append(dict(piece, _need=need))
    result['oversize'] = oversize

    if not fitting:
        return _summarise(result, pieces, offcut_min, rate_per_ft)

    # Group identical demands so the LP stays small.
    buckets = defaultdict(list)
    for piece in fitting:
        buckets[round(piece['_need'], 3)].append(piece)
    demand_mm = sorted(buckets)
    counts = [len(buckets[key]) for key in demand_mm]
    costs = [v / MM_PER_FOOT for v in stock_list]

    patterns = None
    if HAS_SOLVER:
        try:
            patterns, bound, ok = _column_generation(
                demand_mm, counts, capacities, costs)
            if patterns and ok:
                objective, values, _duals = _solve_lp(
                    patterns, counts, costs, integer=True)
                if objective is not None:
                    chosen = []
                    for index, value in enumerate(values):
                        for _ in range(int(round(value))):
                            chosen.append(patterns[index])
                    result['method'] = 'exact'
                    result['lower_bound_feet'] = bound or 0.0
                    gap = (objective or 0.0) - (bound or 0.0)
                    result['gap_feet'] = max(0.0, gap)
                    result['proven_optimal'] = gap <= 1e-6
                    patterns = chosen
                else:
                    patterns = None
        except Exception:                        # pragma: no cover
            # A solver failure must not lose the plan; fall through.
            patterns = None

    if patterns is None:
        patterns = _greedy(demand_mm, counts, capacities, costs)
        result['method'] = 'greedy'
        result['proven_optimal'] = False
        if patterns is None:
            result['feasible'] = False
            return _summarise(result, pieces, offcut_min, rate_per_ft)

    # Turn patterns back into real bars carrying real pieces.
    pool = {key: list(value) for key, value in buckets.items()}
    bars = []
    for stock_index, row in patterns:
        cuts = []
        for item_index, take in enumerate(row):
            key = demand_mm[item_index]
            for _ in range(take):
                if pool[key]:
                    cuts.append(pool[key].pop())
        if not cuts:
            continue
        consumed = sum(piece['_need'] for piece in cuts)
        bars.append({
            'stock_mm': stock_list[stock_index],
            'cuts': cuts,
            'remainder': usable_bar_mm(
                stock_list[stock_index], start_trim, safety_margin) - consumed,
        })
    # Anything the pattern rounding left over still has to be cut.
    leftovers = [piece for items in pool.values() for piece in items]
    for piece in sorted(leftovers, key=lambda p: -p['_need']):
        for bar in bars:
            if piece['_need'] <= bar['remainder'] + 1e-9:
                bar['cuts'].append(piece)
                bar['remainder'] -= piece['_need']
                break
        else:
            stock_index = min(
                (i for i, cap in enumerate(capacities)
                 if piece['_need'] <= cap + 1e-9),
                key=lambda i: costs[i], default=None)
            if stock_index is None:
                result['feasible'] = False
                continue
            bars.append({
                'stock_mm': stock_list[stock_index],
                'cuts': [piece],
                'remainder': capacities[stock_index] - piece['_need'],
            })
    result['bars'] = bars
    return _summarise(result, pieces, offcut_min, rate_per_ft)


def _summarise(result, pieces, offcut_min, rate_per_ft):
    bars = result['bars']
    feet_bought = sum(bar['stock_mm'] for bar in bars) / MM_PER_FOOT
    placed = [piece for bar in bars for piece in bar['cuts']]
    feet_used = sum(piece['length'] for piece in placed) / MM_PER_FOOT
    bars_by_length = {}
    for bar in bars:
        bars_by_length[bar['stock_mm']] = \
            bars_by_length.get(bar['stock_mm'], 0) + 1
    result.update({
        'bar_count': len(bars),
        'bars_by_length': bars_by_length,
        'feet_bought': feet_bought,
        'feet_used': feet_used,
        'waste_feet': feet_bought - feet_used,
        'yield_pct': (feet_used / feet_bought * 100.0) if feet_bought else 0.0,
        'cost': feet_bought * rate_per_ft,
        'placed_count': len(placed),
        'offcuts': sorted(
            (bar['remainder'] for bar in bars
             if bar['remainder'] >= offcut_min), reverse=True),
    })
    return result


def evaluate(pieces, stock_mm_list, kerf=5.0, offcut_min=400.0,
             rate_per_ft=0.0, start_trim=0.0, safety_margin=0.0):
    """Every stock-length option plus Mixed, each solved exactly.

    A single-length option that cannot hold one of the pieces is marked
    infeasible rather than quietly dropping it -- the estimator needs to
    know "16 ft only" is not available today, not be handed a plan
    missing a member.
    """
    stock_list = sorted(float(v) for v in stock_mm_list)
    if not stock_list:
        return {'scenarios': [], 'oversize': list(pieces),
                'chosen_key': None}

    def run(subset):
        return solve(pieces, subset, kerf=kerf, start_trim=start_trim,
                     safety_margin=safety_margin, offcut_min=offcut_min,
                     rate_per_ft=rate_per_ft)

    full = run(stock_list)
    scenarios = []
    for stock_mm in stock_list:
        single = run([stock_mm])
        key = '%g' % round(stock_mm / MM_PER_FOOT, 4)
        # Infeasible when this length cannot take every piece that the
        # full set can.
        feasible = (single['feasible']
                    and single['placed_count'] == full['placed_count'])
        blocked = []
        if not feasible:
            capacity = usable_bar_mm(stock_mm, start_trim, safety_margin)
            blocked = sorted(
                (p['length'] for p in pieces
                 if piece_demand_mm(p['length'], kerf,
                                    p.get('angle') or '45') > capacity),
                reverse=True)[:3]
        single.update({
            'key': key, 'label': '%s ft only' % key,
            'stock_mm': stock_mm, 'feasible': feasible,
            'blocked_by': blocked,
        })
        if not feasible:
            single.update({'bars': [], 'bar_count': 0, 'bars_by_length': {},
                           'feet_bought': 0.0, 'cost': 0.0, 'offcuts': []})
        scenarios.append(single)

    full.update({'key': 'mixed', 'label': 'Mixed', 'stock_mm': 0.0,
                 'blocked_by': []})
    scenarios.append(full)

    usable = [s for s in scenarios if s['feasible'] and s['bar_count']]
    chosen = None
    if usable:
        chosen = min(usable, key=lambda s: (
            round(s['cost'], 6), round(s['feet_bought'], 6),
            scenarios.index(s)))
    return {
        'scenarios': scenarios,
        'oversize': full['oversize'],
        'chosen_key': chosen['key'] if chosen else None,
        'method': full.get('method'),
        'proven_optimal': full.get('proven_optimal'),
        'gap_feet': full.get('gap_feet'),
    }


def scenario_by_key(result, key):
    for scenario in result['scenarios']:
        if scenario['key'] == key and scenario['feasible']:
            return scenario
    for scenario in result['scenarios']:
        if scenario['key'] == result['chosen_key']:
            return scenario
    return None
