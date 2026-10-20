# -*- coding: utf-8 -*-
"""Internal references for profile variants: code-thickness-finish.

A fixed table, not a rule. A value that is not in it gets no reference
and is reported; an abbreviation is never invented.
"""

THICKNESS_CODES = {
    'Normal': 'NOR', 'Standard': 'STD',
    '1.4MM': '14', '1.6MM': '16', '1.8MM': '18', '1.9MM': '19',
    '2MM': '20', '2.5MM': '25', '3MM': '30', '3.8MM': '38', '6MM': '60',
}

FINISH_CODES = {
    'Natural': 'NAT', 'H23 PC RAL': 'H23', 'Brown PC Sahara': 'SAH',
    'Black Multi SS Dull': 'BLK', 'Designer': 'DSG', 'C-Shine': 'CSH',
}


def variant_reference(code, thickness_name, finish_name):
    """(reference, missing). `missing` lists the value names that have no
    abbreviation; the reference is empty then. A profile with no thickness
    dimension is code-finish."""
    missing = []
    parts = [code]
    if thickness_name:
        short = THICKNESS_CODES.get(thickness_name)
        if short:
            parts.append(short)
        else:
            missing.append(thickness_name)
    if finish_name:
        short = FINISH_CODES.get(finish_name)
        if short:
            parts.append(short)
        else:
            missing.append(finish_name)
    if missing or not code:
        return '', missing
    return '-'.join(parts), []
