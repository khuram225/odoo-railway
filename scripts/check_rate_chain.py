#!/usr/bin/env python3
"""Exercise the profile-rate validity chain with the REAL implementation.

resolve_chain() decides when each version of a price stops applying.
Getting it wrong is expensive and quiet: a rate that closes a day late
overlaps its successor and the lookup picks whichever sorts first; a
rate that closes a day early leaves a gap where a quote silently has no
price at all. Neither shows up as an error anywhere.

Imports the real function out of the model file, which is why that
function is kept free of Odoo imports -- a reimplementation here would
share none of its bugs and prove nothing.
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = (ROOT / 'odoo' / 'addons' / 'aw_fenestration_core' / 'models'
         / 'profile_rate.py')


def load_resolver():
    """Read just the Odoo-free part of the model file.

    The module as a whole imports odoo, so it cannot be imported here.
    The function and its own imports are lifted out by name instead.
    """
    source = MODEL.read_text(encoding='utf-8')
    start = source.index('def resolve_chain(')
    end = source.index('\nclass ')
    namespace = {}
    exec('from datetime import timedelta\n\n' + source[start:end], namespace)
    return namespace['resolve_chain']


def main():
    resolve_chain = load_resolver()
    d = date
    problems = []

    def check(label, entries, expected):
        actual = resolve_chain(entries)
        if actual != expected:
            problems.append('%s\n      got      %s\n      expected %s'
                            % (label, actual, expected))

    # One version, running forever.
    check('single open-ended rate',
          [(d(2026, 1, 1), None)],
          [(False, False)])

    # Two versions: the first ends the day before the second starts.
    check('superseded by a later list',
          [(d(2026, 1, 1), None), (d(2026, 7, 1), None)],
          [(d(2026, 6, 30), True), (False, False)])

    # BACK-DATED import: a list dated between two existing ones has to
    # shorten the EARLIER record, which is the case a forward-only
    # implementation gets wrong.
    check('back-dated list inserted in the middle',
          [(d(2026, 1, 1), None), (d(2026, 4, 1), None),
           (d(2026, 7, 1), None)],
          [(d(2026, 3, 31), True), (d(2026, 6, 30), True), (False, False)])

    # A manual end date BEFORE the successor wins, and means expired,
    # not superseded -- the distinction the missing-rate warning hangs
    # on.
    check('manual end date earlier than the successor',
          [(d(2026, 1, 1), d(2026, 3, 1)), (d(2026, 7, 1), None)],
          [(d(2026, 3, 1), False), (False, False)])

    # A manual end date AFTER the successor does not extend it past the
    # replacement: two live prices for one day is worse than a short one.
    check('manual end date later than the successor',
          [(d(2026, 1, 1), d(2026, 12, 31)), (d(2026, 7, 1), None)],
          [(d(2026, 6, 30), True), (False, False)])

    # Manual end date with nothing after it: expired.
    check('retired with no successor',
          [(d(2026, 1, 1), d(2026, 3, 1))],
          [(d(2026, 3, 1), False)])

    # End date falling exactly on the successor's boundary stays
    # superseded, because the chain end is <= the manual one.
    check('end date exactly on the boundary',
          [(d(2026, 1, 1), d(2026, 6, 30)), (d(2026, 7, 1), None)],
          [(d(2026, 6, 30), True), (False, False)])

    # Two rows sharing a date_from must not close each other, which
    # would set a date_to BEFORE their own date_from.
    check('duplicate start dates',
          [(d(2026, 1, 1), None), (d(2026, 1, 1), None)],
          [(False, False), (False, False)])

    check('duplicates followed by a real successor',
          [(d(2026, 1, 1), None), (d(2026, 1, 1), None),
           (d(2026, 7, 1), None)],
          [(d(2026, 6, 30), True), (d(2026, 6, 30), True), (False, False)])

    # No gap and no overlap anywhere in a long chain.
    chain = [(d(2026, 1, 1), None), (d(2026, 3, 1), None),
             (d(2026, 6, 1), None), (d(2027, 1, 1), None)]
    resolved = resolve_chain(chain)
    for index in range(len(chain) - 1):
        date_to = resolved[index][0]
        next_from = chain[index + 1][0]
        if not date_to or (next_from - date_to).days != 1:
            problems.append(
                'chain continuity: version %s ends %s but the next starts '
                '%s' % (index, date_to, next_from))

    if problems:
        print('Rate chain problems:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('Rate validity chain correct: 9 case(s) plus continuity, '
          'including back-dated inserts and manual end dates.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
