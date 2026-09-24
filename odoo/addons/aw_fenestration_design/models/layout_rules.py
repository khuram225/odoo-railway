# -*- coding: utf-8 -*-
"""Layout-JSON rules, as plain Python with NO Odoo imports.

Deliberately importable on its own, so scripts/check_preset_layouts.py
can run the exact same validation the upgrade runs. The bug that led to
this: OPN-VNT was the first seeded preset with a nested container, and
the validation treated every leaf as needing a leaf type, so the whole
module upgrade failed with ParseError. Every check in this repo ran on
the client side, so nothing was watching the server-side rule.
"""

# Matches aw.design.MAX_NESTING_DEPTH: a panel may be subdivided, its
# sub-panels subdivided again, and no further.
MAX_NESTING_DEPTH = 3


def leaf_type_codes(data):
    """Every leaf type code a layout would actually create.

    Recurses, and skips containers: a leaf holding `rows` is a container,
    not a panel, and has no type of its own. Used by the Series filter,
    which would otherwise see a None for every nested preset and decide
    no Series could host it.
    """
    codes = set()

    def walk(rows):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            for leaf in row.get('leaves') or []:
                if not isinstance(leaf, dict):
                    continue
                if leaf.get('rows'):
                    walk(leaf['rows'])
                elif leaf.get('type'):
                    codes.add(leaf['type'])

    walk((data or {}).get('rows'))
    return codes


def attachment_codes(data):
    """Mesh, infill and grid codes a layout refers to, by kind.

    Presets refer to a type by CODE rather than by id so they survive the
    records being recreated -- the same reason leaf types are referred to
    that way.
    """
    found = {'mesh': set(), 'infill': set(), 'grid': set()}

    def walk(rows):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            for leaf in row.get('leaves') or []:
                if not isinstance(leaf, dict):
                    continue
                if leaf.get('rows'):
                    walk(leaf['rows'])
                    continue
                if leaf.get('mesh'):
                    found['mesh'].add(leaf['mesh'])
                if leaf.get('infill'):
                    found['infill'].add(leaf['infill'])
                grid = leaf.get('grid')
                if isinstance(grid, dict) and grid.get('pattern'):
                    found['grid'].add(grid['pattern'])

    walk((data or {}).get('rows'))
    return found


def validate_layout(data, known_codes, max_depth=MAX_NESTING_DEPTH,
                    known_mesh=None, known_infill=None, known_grid=None):
    """Return a list of human-readable problems; empty means valid.

    Returning errors rather than raising keeps this usable both from an
    Odoo constraint and from a standalone script.
    """
    if not isinstance(data, dict):
        return ['Layout must be an object with a "rows" list.']

    errors = []

    def walk(rows, depth, where):
        if not isinstance(rows, list) or not rows:
            errors.append('%s needs a non-empty "rows" list.' % where)
            return
        if depth > max_depth:
            errors.append(
                '%s nests deeper than %s levels.' % (where, max_depth))
            return
        for i, row in enumerate(rows, 1):
            row_where = '%s row %s' % (where, i)
            leaves = row.get('leaves') if isinstance(row, dict) else None
            if not isinstance(leaves, list) or not leaves:
                errors.append(
                    '%s needs a non-empty "leaves" list.' % row_where)
                continue
            for j, leaf in enumerate(leaves, 1):
                leaf_where = '%s leaf %s' % (row_where, j)
                if not isinstance(leaf, dict):
                    errors.append('%s must be an object.' % leaf_where)
                    continue
                nested = leaf.get('rows')
                if nested:
                    # A container is not a panel: it holds rows instead of
                    # being one, so a leaf type here is a contradiction.
                    if leaf.get('type'):
                        errors.append(
                            '%s is subdivided, so it must not carry a leaf '
                            'type (it has %r).' % (leaf_where, leaf['type']))
                    walk(nested, depth + 1, leaf_where)
                else:
                    code = leaf.get('type')
                    if code not in known_codes:
                        errors.append(
                            '%s uses unknown leaf type code %r. Known codes: '
                            '%s' % (leaf_where, code,
                                    ', '.join(sorted(known_codes))))
                    # Attachments, checked only when the caller supplies
                    # the catalogues -- the Odoo constraint always does,
                    # a bare call may not.
                    for key, known, label in (
                        ('mesh', known_mesh, 'mesh type'),
                        ('infill', known_infill, 'infill type'),
                    ):
                        value = leaf.get(key)
                        if value and known is not None and value not in known:
                            errors.append(
                                '%s uses unknown %s code %r.'
                                % (leaf_where, label, value))
                    grid = leaf.get('grid')
                    if grid is not None:
                        if not isinstance(grid, dict):
                            errors.append(
                                '%s "grid" must be an object with a '
                                '"pattern".' % leaf_where)
                        elif (grid.get('pattern') and known_grid is not None
                                and grid['pattern'] not in known_grid):
                            errors.append(
                                '%s uses unknown grid pattern code %r.'
                                % (leaf_where, grid['pattern']))

    walk(data.get('rows'), 1, 'Layout')
    return errors
