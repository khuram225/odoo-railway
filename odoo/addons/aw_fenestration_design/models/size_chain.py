# -*- coding: utf-8 -*-
"""The size-rule chain, free of Odoo so a script can run the REAL function
(`scripts/check_size_chain.py`), like `formula.py` and `resolve_chain`.

Each piece starts from the FINAL length of the piece before it:

    window -> frame -> divider -> sash side -> sash bead / lock bar

A rule says, for one piece kind of one series, where it starts from and an
offset in mm. A kind with no filled rule keeps the length the spec's formula
gave. The +/- adjustment is added on top of the rule length by the caller's
`shift`, and so is part of the FINAL length the next piece starts from; a
length typed by hand is applied later and is not part of the chain.
"""

KINDS = [
    ('frame', 'Frame'),
    ('divider', 'Divider'),
    ('sash_side', 'Sash side'),
    ('sash_bead', 'Sash bead'),
    ('lock_bar', 'Lock bar'),
]
STARTS = [
    ('window', 'Window'),
    ('frame', 'Frame'),
    ('divider', 'Divider'),
    ('sash_side', 'Sash side'),
]
KIND_LABEL = dict(KINDS)
START_LABEL = dict(STARTS)

# Where a kind sits in the chain. Beads and the lock bar are both fitted to
# the sash side, and nothing starts from either.
RANK = {'window': 0, 'frame': 1, 'divider': 2, 'sash_side': 3,
        'sash_bead': 4, 'lock_bar': 4}

# aw.profile.position.part_group -> size kind. A position whose group is not
# here never follows a rule, and the checks say so.
KIND_BY_GROUP = {
    'outer_frame': 'frame',
    'dividers': 'divider',
    'sashes': 'sash_side',
    'beads': 'sash_bead',
    'lock': 'lock_bar',
}

SIDE = {1: 'top', 2: 'right side', 3: 'bottom', 4: 'left side'}
MM_PER_INCH = 25.4


def kind_for_group(group):
    return KIND_BY_GROUP.get(group or '')


def allowed_starts(kind):
    """The starting points a kind may use: only what comes before it."""
    return [code for code, _label in STARTS if RANK[code] < RANK[kind]]


def inches(mm):
    text = ('%.2f' % (mm / MM_PER_INCH)).rstrip('0').rstrip('.')
    return text or '0'


def _where(piece):
    """'left side', 'top', 'P2' or '' for a piece, for the source text."""
    if piece.get('edge') in SIDE:
        return SIDE[piece['edge']]
    if piece.get('panel_no'):
        return 'P%s' % piece['panel_no']
    return ''


def _find_parent(piece, start, done, window_w, window_h):
    """(length, text, level) of the piece to start from.

    Walks DOWN from `start` when there is no such piece in this window (a
    divider rule on a window with no divider starts from the frame), taking
    the first piece of the matching orientation, the same panel's first.
    """
    orient = piece['orient']
    levels = [code for code, _l in STARTS]
    for level in reversed(levels[:levels.index(start) + 1]):
        if level == 'window':
            if orient == 'v':
                return window_h, 'window height', level
            return window_w, 'window width', level
        candidates = [p for p in done.get(level, ())
                      if p['orient'] == orient]
        if not candidates:
            continue
        same_panel = [p for p in candidates
                      if piece.get('panel_no')
                      and p.get('panel_no') == piece['panel_no']]
        parent = (same_panel or candidates)[0]
        text = ' '.join(x for x in (
            START_LABEL[level].lower(), _where(parent)) if x)
        return parent['final'], text, level
    return None, '', ''


def resolve(pieces, rules, window_w, window_h):
    """Apply `rules` to `pieces`; return {piece id: result} for the pieces
    whose kind has a rule.

    pieces: dicts with `id`, `kind` (or None), `orient` ('h', 'v' or None),
      `panel_no`, `edge` (1 top, 2 right, 3 bottom, 4 left, or 0), `length`
      (what the spec's formula gave, mm), `shift` (the adjustment that goes
      on top, mm) and `cut_on_site`.
    rules: {kind: (starts_from, offset_mm)}, filled rules only.

    A result has `applied`, `length` (the rule length, before the shift),
    `final` (with the shift), `note` and `problem`. A piece whose rule gives
    0 or less, or whose orientation is unknown, keeps its formula length and
    carries a `problem`.
    """
    results = {}
    done = {}
    ordered = sorted(
        (p for p in pieces if p.get('kind') in RANK),
        key=lambda p: RANK[p['kind']])
    for piece in ordered:
        kind = piece['kind']
        base = piece['length'] or 0.0
        shift = 0.0 if piece.get('cut_on_site') else (piece.get('shift') or 0.0)
        result = {'applied': False, 'length': base,
                  'final': max(0.0, base + shift) if shift else base,
                  'note': '', 'problem': ''}
        rule = rules.get(kind)
        if (rule and rule[0] and not piece.get('cut_on_site')
                and rule[0] in allowed_starts(kind)):
            start, offset = rule
            if piece['orient'] not in ('h', 'v'):
                result['problem'] = (
                    "the piece has no known direction, so its rule "
                    "cannot be applied.")
            else:
                parent, text, level = _find_parent(
                    piece, start, done, window_w, window_h)
                length = (parent or 0.0) + offset
                note = '%s: %s %s in %s %s in' % (
                    KIND_LABEL[kind].lower(), text, inches(parent or 0.0),
                    '+' if offset > 0 else '-', inches(abs(offset)))
                if level != start:
                    note += ' (no %s piece here)' % START_LABEL[start].lower()
                if length <= 0:
                    result['problem'] = (
                        "%s would be %s mm long, so the spec's formula "
                        "is used." % (note, round(length)))
                else:
                    result.update(
                        applied=True, length=length, note=note,
                        final=max(0.0, length + shift))
        results[piece['id']] = result
        if not piece.get('cut_on_site'):
            done.setdefault(kind, []).append(dict(
                piece, final=result['final']))
    return results
