#!/usr/bin/env python3
"""The cost rule: the newer of the list rate and the last purchase price.

Runs the REAL `decide()` out of aw_fenestration_design/models/cost_rule.py
(Odoo-free for exactly this). The cases are ones whose answer can be read
off by hand; the text is checked because it is what a person reads to see
where a cost came from.
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

MODULE = (Path(__file__).resolve().parent.parent / 'odoo' / 'addons'
          / 'aw_fenestration_design' / 'models' / 'cost_rule.py')
spec = importlib.util.spec_from_file_location('aw_cost_rule', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
decide = mod.decide

TODAY = date(2026, 11, 9)
JAN1, NOV8 = date(2026, 1, 1), date(2026, 11, 8)

CASES = [
    # (list, list date, level, lpp, lpp date, max age, kind, cost, text)
    (765, JAN1, 'exact', 0, None, 180, 'list', 765,
     'list 765 from 1 Jan'),
    (0, None, '', 812, NOV8, 180, 'lpp', 812, 'LPP 812 from 8 Nov'),
    (765, JAN1, 'exact', 812, NOV8, 180, 'lpp', 812,
     'LPP 812 from 8 Nov'),                       # the LPP is newer
    (830, date(2026, 11, 8), 'exact', 812, NOV8, 180, 'lpp', 812,
     'LPP 812 from 8 Nov'),                       # same date: the LPP
    (830, date(2026, 11, 9), 'exact', 812, NOV8, 180, 'list', 830,
     'list 830 from 9 Nov'),                      # the list is newer
    (765, JAN1, 'thickness', 812, NOV8, 180, 'lpp', 812,
     'LPP 812 from 8 Nov (list was an estimate)'),    # a fallback list
    (765, date(2026, 11, 9), 'template', 812, NOV8, 180, 'lpp', 812,
     'LPP 812 from 8 Nov (list was an estimate)'),    # even a newer one
    (765, JAN1, 'thickness', 0, None, 180, 'list', 765,
     'list 765 from 1 Jan (any finish)'),
    (765, JAN1, 'exact', 812, date(2026, 5, 1), 180, 'list', 765,
     'list 765 from 1 Jan (LPP 812 from 1 May ignored: older than 180 days)'),
    (765, JAN1, 'exact', 812, date(2026, 5, 13), 180, 'lpp', 812,
     'LPP 812 from 13 May'),                      # exactly 180 days: kept
    (0, None, '', 812, date(2026, 5, 1), 180, 'none', 0.0,
     'no list rate and no LPP (LPP 812 from 1 May ignored: older than '
     '180 days)'),
    (0, None, '', 0, None, 180, 'none', 0.0, 'no list rate and no LPP'),
    (765.5, JAN1, 'exact', 0, None, 180, 'list', 765.5,
     'list 765.50 from 1 Jan'),
    (765, JAN1, 'exact', 812, date(2026, 11, 20), 180, 'list', 765,
     'list 765 from 1 Jan'),                      # after the day costed
    (0, None, '', 812, date(2025, 1, 1), None, 'lpp', 812,
     'LPP 812 from 1 Jan'),                       # no age limit
]


def main():
    failed = 0
    for (lp, ld, level, pp, pd, age, kind, cost, text) in CASES:
        got = decide(lp, ld, level, pp, pd, TODAY, age)
        ok = (got['kind'], got['cost'], got['text']) == (kind, cost, text)
        if not ok:
            failed += 1
            print('FAIL list=%s %s %s lpp=%s %s age=%s\n  want %s %s "%s"\n'
                  '  got  %s %s "%s"' % (
                      lp, ld, level, pp, pd, age, kind, cost, text,
                      got['kind'], got['cost'], got['text']))
    if failed:
        print('%d of %d cost-rule case(s) failed' % (failed, len(CASES)))
        return 1
    print('Cost rule correct: %d case(s): the newer of list and LPP, the LPP '
          'on a tie, the age limit, a fallback list is an estimate, and the '
          'words say where the figure came from.' % len(CASES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
