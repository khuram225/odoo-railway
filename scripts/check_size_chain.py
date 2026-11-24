#!/usr/bin/env python3
"""The size-rule chain, run as the REAL function (size_chain.py is Odoo-free).

Covers what the Odoo tests cannot make cheaply: both directions, the lock
bar, a rule that gives nothing, a missing start, cut-on-site pieces, and that
no rule means no change.
"""
import importlib.util
import sys
from pathlib import Path

MODULE = (Path(__file__).resolve().parent.parent / 'odoo' / 'addons'
          / 'aw_fenestration_design' / 'models' / 'size_chain.py')
spec = importlib.util.spec_from_file_location('size_chain', MODULE)
chain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chain)

failures = []


def check(name, ok, detail=''):
    if not ok:
        failures.append('%s %s' % (name, detail))


def piece(pid, kind, orient, length, edge=0, panel=0, shift=0.0, site=False):
    return {'id': pid, 'kind': kind, 'orient': orient, 'length': length,
            'edge': edge, 'panel_no': panel, 'shift': shift,
            'cut_on_site': site}


PIECES = [
    piece(1, 'frame', 'h', 3000.0, edge=1),
    piece(2, 'frame', 'v', 1500.0, edge=2),
    piece(3, 'frame', 'v', 1500.0, edge=4),
    piece(4, 'divider', 'v', 1500.0),
    piece(5, 'sash_side', 'v', 1500.0, edge=2, panel=1),
    piece(6, 'sash_side', 'h', 900.0, edge=1, panel=1),
    piece(7, 'sash_bead', 'v', 1450.0, edge=2, panel=1),
    piece(8, 'lock_bar', 'v', 1200.0, panel=1),
    piece(9, None, 'v', 77.0),
]

# no rules, no change
check('no rules', chain.resolve(PIECES, {}, 3000.0, 1500.0).keys()
      == {1, 2, 3, 4, 5, 6, 7, 8}
      and not any(r['applied'] for r in chain.resolve(
          PIECES, {}, 3000.0, 1500.0).values()))

rules = {'divider': ('frame', -50.8), 'sash_side': ('divider', -25.4),
         'sash_bead': ('sash_side', -50.8), 'lock_bar': ('sash_side', -101.6)}
out = chain.resolve(PIECES, rules, 3000.0, 1500.0)
check('divider', abs(out[4]['length'] - 1449.2) < 1e-6, out[4])
check('divider note', out[4]['note'] == 'divider: frame right side 59.06 in '
      '- 2 in', out[4]['note'])
check('vertical sash from divider', abs(out[5]['length'] - 1423.8) < 1e-6)
# no horizontal divider: the top sash side falls back to the frame's width
check('horizontal falls back', abs(out[6]['length'] - (3000 - 25.4)) < 1e-6
      and '(no divider piece here)' in out[6]['note'], out[6])
check('bead from the sash side', abs(out[7]['length'] - 1373.0) < 1e-6)
check('lock bar from the sash side', abs(out[8]['length'] - 1322.2) < 1e-6)
check('unkinded piece is not in the result', 9 not in out)

# the shift goes on top and is part of what the next piece starts from
shifted = [dict(p, shift=10.0) if p['id'] == 2 else p for p in PIECES]
out = chain.resolve(shifted, {'divider': ('frame', -50.8)}, 3000.0, 1500.0)
check('shift reaches the next piece', abs(out[4]['length'] - 1459.2) < 1e-6)
check('final carries the shift', abs(out[2]['final'] - 1510.0) < 1e-6)

# a rule giving 0 or less keeps the formula and says so
out = chain.resolve(PIECES, {'divider': ('frame', -9999.0)}, 3000.0, 1500.0)
check('zero keeps the formula', not out[4]['applied']
      and out[4]['length'] == 1500.0 and out[4]['problem'], out[4])

# a start from later in the chain is ignored
out = chain.resolve(PIECES, {'frame': ('divider', 0.0)}, 3000.0, 1500.0)
check('start after the piece is ignored', not out[1]['applied'])

# cut on site: not ruled, and never a starting point
site = [dict(p, cut_on_site=True) if p['id'] in (2, 3) else p
        for p in PIECES]
out = chain.resolve(site, {'divider': ('frame', -50.8)}, 3000.0, 1500.0)
check('cut-on-site frame is skipped, so the window height is used',
      abs(out[4]['length'] - (1500.0 - 50.8)) < 1e-6
      and 'window height' in out[4]['note'], out[4])

# window as the start
out = chain.resolve(PIECES, {'frame': ('window', -100.0)}, 3000.0, 1500.0)
check('frame from the window', abs(out[1]['length'] - 2900.0) < 1e-6
      and abs(out[2]['length'] - 1400.0) < 1e-6, out[1])

# an unknown direction is a problem, not a guess
odd = [piece(1, 'divider', None, 1500.0)]
out = chain.resolve(odd, {'divider': ('frame', 0.0)}, 3000.0, 1500.0)
check('unknown direction', not out[1]['applied'] and out[1]['problem'])

# groups and starts
check('groups', chain.kind_for_group('dividers') == 'divider'
      and chain.kind_for_group('fly_screen') is None
      and chain.kind_for_group(False) is None)
check('allowed starts', chain.allowed_starts('frame') == ['window']
      and chain.allowed_starts('lock_bar') == [
          'window', 'frame', 'divider', 'sash_side'])

if failures:
    print('FAIL check_size_chain:')
    for failure in failures:
        print('  -', failure)
    sys.exit(1)
print('check_size_chain: ok')
