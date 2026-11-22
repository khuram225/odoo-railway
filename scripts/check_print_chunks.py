#!/usr/bin/env python3
"""Runs the REAL print_chunks functions (Odoo-free) on made-up bodies: how a report is
cut into wkhtmltopdf runs, that no unit is lost, doubled or reordered, that a page
break is taken off the last unit of each part only, and that the header and footer
children follow their bodies. See models/print_chunks.py for why."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    'aw_print_chunks',
    ROOT / 'odoo' / 'addons' / 'aw_fenestration_design' / 'models' / 'print_chunks.py')
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

failures = []


def check(name, ok, detail=''):
    if not ok:
        failures.append('%s %s' % (name, detail))


def unit(i, last=False):
    brk = '' if last else pc.BREAK
    return '<div id="u%d" style="font-size:13px; %s">sheet %d</div>' % (i, brk, i)


def body(n, charset='<meta charset="x"/>'):
    parts = [pc.START + unit(i, i == n - 1) for i in range(n)]
    return charset + '<div class="article">' + ''.join(parts) + pc.END + '</div>'


# -- one body of many units ---------------------------------------------------
for n in (1, 7, 10, 11, 25, 100):
    items = pc.expand([body(n)], 10)
    groups = pc.runs(items, 10)
    check('n=%d: parts' % n, len(items) == -(-n // 10), len(items))
    text = ''.join(b for _i, b, _w in items)
    ids = [int(x) for x in __import__('re').findall(r'id="u(\d+)"', text)]
    check('n=%d: every unit once, in order' % n, ids == list(range(n)), ids[:5])
    check('n=%d: no marker left' % n, 'o_aw_split' not in text)
    for _i, b, _w in items:
        check('n=%d: charset and wrapper kept in every part' % n,
              b.startswith('<meta charset="x"/><div class="article">')
              and b.endswith('</div>'))
        last = b.rfind('id="u')
        check('n=%d: the last unit of a part has no break' % n,
              pc.BREAK not in b[last:])
    check('n=%d: runs hold at most 10' % n, all(len(g) <= 10 for g in groups))
    # the breaks BETWEEN units of a part are kept
    for _i, b, _w in items:
        units = b.count('id="u')
        check('n=%d: breaks inside a part kept' % n,
              b.count(pc.BREAK) == units - 1, (units, b.count(pc.BREAK)))

# -- several bodies (one per window) -------------------------------------------
items = pc.expand(['<p>w%d</p>' % i for i in range(23)], 10)
groups = pc.runs(items, 10)
check('23 bodies: 3 runs', [len(g) for g in groups] == [10, 10, 3], [len(g) for g in groups])
check('23 bodies: same order, untouched',
      [b for _i, b, _w in items] == ['<p>w%d</p>' % i for i in range(23)])

# -- a body with no markers stays one body ----------------------------------------
check('no markers: one body, as is', pc.expand(['<p>x</p>'], 10) == [(0, '<p>x</p>', 1.0)])
check('split_units of nothing', pc.split_units('<p>x</p>') is None)

# -- header / footer children follow their bodies -----------------------------------
html = ('<!DOCTYPE html><html><head><base href="/"/></head><body>'
        '<div id="minimal_layout_report_headers">'
        + ''.join('<div class="header">h%d</div>' % i for i in range(4)) +
        '</div></body></html>')
out = pc.slice_children(html, 'minimal_layout_report_headers', [2, 3])
check('header: kept children only, in order',
      'h2' in out and 'h3' in out and 'h0' not in out and 'h1' not in out
      and out.index('h2') < out.index('h3'), out)
check('header: doctype and head kept', out.startswith('<!DOCTYPE html>') and 'base href' in out)
out = pc.slice_children(html, 'minimal_layout_report_headers', [0, 0, 0])
check('header: a cut body repeats its own', out.count('h0') == 3, out)
check('header: none stays none', pc.slice_children(None, 'x', [0]) is None)
check('header: unknown id unchanged', pc.slice_children(html, 'nope', [0]) == html)

# -- a body Odoo renders is a Markup, which escapes any plain str added to it ---------
class Markupish(str):
    """What markupsafe.Markup does: adding a plain str to it escapes that str."""
    def __add__(self, other):
        if type(other) is not Markupish:
            other = str(other).replace('<', '&lt;').replace('>', '&gt;')
        return Markupish(str.__add__(self, other))

    def __getitem__(self, key):
        return Markupish(str.__getitem__(self, key))

marked = Markupish(body(25))
items = pc.expand([marked], 10)
check('a Markup body is cut into plain text', all('&lt;' not in b for _i, b, _w in items)
      and all(type(b) is str for _i, b, _w in items), [b[:80] for _i, b, _w in items][:1])
check('a Markup body keeps every unit', ''.join(b for _i, b, _w in items).count('id="u') == 25)

# -- weights: a heavy unit (a sticker page, 2) fills a run sooner ------------------
def wbody(weights):
    parts = [pc.start_marker(w) + unit(i, i == len(weights) - 1) for i, w in enumerate(weights)]
    return '<div class="article">' + ''.join(parts) + pc.END + '</div>'

items = pc.expand([wbody([2.0] * 7)], 10)
check('weight 2 x 7 -> parts of 5 and 2', [b.count('id="u') for _i, b, _w in items] == [5, 2],
      [b.count('id="u') for _i, b, _w in items])
items = pc.expand([wbody([0.25] * 90)], 10)
check('weight 0.25 x 90 -> parts of 40, 40, 10', [b.count('id="u') for _i, b, _w in items] == [40, 40, 10],
      [b.count('id="u') for _i, b, _w in items])
check('one heavy unit still gets a part', len(pc.expand([wbody([30.0, 1.0])], 10)) == 2)
groups = pc.runs(pc.expand([wbody([4.0] * 9)], 10), 10)
check('parts are runs of their own weight', all(sum(w for _i, _b, w in g) <= 10 for g in groups))
check('weights are read', pc.split_units(wbody([0.25, 2.0]))[1][0][1] == 0.25
      and pc.split_units(wbody([0.25, 2.0]))[1][1][1] == 2.0)

# -- the footer says which part it is -------------------------------------------------
foot = '<div>Page <span class="page"></span> / <span class="topage"></span></div>'
out = pc.label_part(foot, 2, 8)
check('footer: Part 2 of 8 in front of the page number',
      'Part 2 of 8, Page <span class="page">' in out, out)
check('footer: none stays none', pc.label_part(None, 1, 2) is None)
check('was_cut', pc.was_cut([body(3)]) and not pc.was_cut(['<p>x</p>']))

if failures:
    print('print chunks: %d problem(s)' % len(failures))
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('print chunks: units cut, ordered, breaks and header children right')
