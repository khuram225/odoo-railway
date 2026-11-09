# -*- coding: utf-8 -*-
"""The cost rule, Odoo-free (`scripts/check_cost_rule.py` runs it).

For one vendor + profile + thickness + finish the current cost per ft is
whichever is NEWER of

* the list rate (dated by its effective date), and
* the last purchase price, LPP (dated by the PO's confirmation);

on the same date the LPP wins. An LPP older than the maximum age (180 days
by default) is ignored, and so is one dated after the day being costed. When
only one exists it is used. A list rate found only by a fallback (the vendor
lists the profile by thickness only, or for any finish) is an ESTIMATE: an
exact LPP within the age wins over it whatever the dates.

`decide()` returns the cost and the words that say where it came from, e.g.
"list 765 from 1 Jan" or "LPP 812 from 8 Nov (list was an estimate)".
"""
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
          'Oct', 'Nov', 'Dec')
DEFAULT_MAX_AGE_DAYS = 180

LEVEL_WORDS = {
    'exact': '',
    'thickness': ' (any finish)',
    'template': ' (any thickness and finish)',
}


def money(value):
    """765, 812.5, 1,250.25: whole numbers without decimals."""
    if abs(value - round(value)) < 0.005:
        return '{:,.0f}'.format(value)
    return '{:,.2f}'.format(value)


def short_date(day):
    return '%d %s' % (day.day, MONTHS[day.month - 1])


def decide(list_price, list_date, list_level, lpp_price, lpp_date, on_date,
           max_age_days=DEFAULT_MAX_AGE_DAYS):
    """{'kind': 'list' | 'lpp' | 'none', 'cost', 'date', 'text'}"""
    has_list = bool(list_price) and list_date is not None
    lpp_ignored = ''
    has_lpp = bool(lpp_price) and lpp_date is not None
    if has_lpp:
        age = (on_date - lpp_date).days
        if age < 0:
            has_lpp = False                    # after the day being costed
        elif max_age_days is not None and age > max_age_days:
            has_lpp = False
            lpp_ignored = ' (LPP %s from %s ignored: older than %s days)' % (
                money(lpp_price), short_date(lpp_date), max_age_days)

    def from_list(note=''):
        return {
            'kind': 'list', 'cost': list_price, 'date': list_date,
            'text': 'list %s from %s%s%s' % (
                money(list_price), short_date(list_date),
                LEVEL_WORDS.get(list_level, ''), note)}

    def from_lpp(note=''):
        return {
            'kind': 'lpp', 'cost': lpp_price, 'date': lpp_date,
            'text': 'LPP %s from %s%s' % (
                money(lpp_price), short_date(lpp_date), note)}

    if has_list and has_lpp:
        if list_level and list_level != 'exact':
            return from_lpp(' (list was an estimate)')
        if lpp_date >= list_date:
            return from_lpp()
        return from_list()
    if has_lpp:
        return from_lpp()
    if has_list:
        return from_list(lpp_ignored)
    return {'kind': 'none', 'cost': 0.0, 'date': None,
            'text': 'no list rate and no LPP%s' % lpp_ignored}
