#!/usr/bin/env python3
"""Runs the REAL drawing_mark functions (Odoo-free): the mark a copied drawing carries
is written, read back, never doubled, safe for odd refs, still well-formed XML, and the
print code redraws a marked drawing as it does an unmarked one."""
import importlib.util
import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / 'odoo' / 'addons' / 'aw_fenestration_design' / 'models'
DATA = ROOT / 'odoo' / 'addons' / 'aw_fenestration_design' / 'tests' / 'data'


def load(name):
    spec = importlib.util.spec_from_file_location('aw_' + name, MODELS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dm = load('drawing_mark')
ep = load('elevation_print')
failures = []


def check(name, ok, detail=''):
    if not ok:
        failures.append('%s %s' % (name, detail))


svg = (DATA / 'elevation_W21_two_casements.svg').read_text(encoding='utf-8')
check('an own drawing has no mark', dm.read_mark(svg) is None)

marked = dm.mark(svg, 'W1', dm.size_text(2590.8, 2514.6))
check('the mark reads back', dm.read_mark(marked) == ('W1', '2590.8x2514.6'), dm.read_mark(marked))
check('still well-formed XML', etree.fromstring(marked.encode('utf-8')) is not None)
check('only the root is touched', marked.count('data-aw-from') == 1 and marked.replace(
    ' data-aw-from="W1" data-aw-size="2590.8x2514.6"', '') == svg)
check('a mark is never doubled (a copy of a copy keeps the original source)',
      dm.mark(marked, 'W9', '1x1') == marked)

odd = dm.mark(svg, 'GF "BATH" <1> & co', '1.0x2.0')
check('an odd ref survives', dm.read_mark(odd) == ('GF "BATH" <1> & co', '1.0x2.0'), dm.read_mark(odd))
check('an odd ref is still well-formed XML', etree.fromstring(odd.encode('utf-8')) is not None)
check('no svg, no mark', dm.mark('', 'W1', 'x') == '' and dm.read_mark(None) is None)

# the printing code treats a marked drawing like any other
plain = ep.print_for_paper(svg, (59.0, 86.0), 6.0, min_paper_pt=6.0)
with_mark = ep.print_for_paper(marked, (59.0, 86.0), 6.0, min_paper_pt=6.0)
check('a marked drawing is redrawn at print size', with_mark['redrawn'])
check('and comes out the same size and label size',
      abs(plain['width_mm'] - with_mark['width_mm']) < 1e-6
      and abs(plain['height_mm'] - with_mark['height_mm']) < 1e-6
      and abs(plain['label_pt'] - with_mark['label_pt']) < 1e-6,
      (plain['label_pt'], with_mark['label_pt']))

if failures:
    print('drawing mark: %d problem(s)' % len(failures))
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('drawing mark: written, read back, never doubled, well-formed, printed like any drawing')
