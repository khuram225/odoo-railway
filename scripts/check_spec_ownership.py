#!/usr/bin/env python3
"""The parts of a window come from its Specification, and from one door.

Phase 7d moved profile and hardware lines off `aw.profile.section` /
`aw.hardware.set` and onto `aw.window.template` (the Spec). Nine
separate places read those lines -- the explosion, the checks, the
costing, the divider options, the Spec tab payload, the override
validation, the lock bar, save-as-spec and the design form -- and every
one of them now goes through `_spec_profile_lines()` or
`_spec_hardware_lines()` on `aw.design`.

That is the invariant worth checking, because the failure is silent in
the worst way. A reader left on `self.profile_section_id.line_ids` does
not raise: after the migration the section is EMPTY, so it returns
nothing, and the design quietly explodes to a BOM with no profiles in
it. No error, no warning, a quote for a window made of glass and air.

So this rejects any read of `.line_ids` off the legacy section or
hardware set anywhere in our design module, and any `.section_id` /
`.set_id` comparison, which is how the divider-option code used to
decide whether a chosen alternative belonged to this design.

`aw_fenestration_core` is exempt by design: it still owns both models,
their forms and the migration that empties them.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / 'odoo' / 'addons' / 'aw_fenestration_design'

# The two accessors every reader must go through, and the model they
# live on. Named so a rename here fails loudly rather than quietly
# turning the check off.
DOORS = ('_spec_profile_lines', '_spec_hardware_lines')

# attribute chains that mean "reading the legacy owner's lines"
BANNED_CHAINS = (
    ('profile_section_id', 'line_ids'),
    ('hardware_set_id', 'line_ids'),
)
# and the legacy ownership fields, which no longer decide anything
BANNED_ATTRS = ('section_id', 'set_id')


def chains(tree):
    """Every (outer, inner) attribute pair, e.g. a.b.c -> (b, c)."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if isinstance(node.value, ast.Attribute):
            found.append(((node.value.attr, node.attr), node.lineno))
    return found


def plain_attrs(tree):
    """Every `<something>.attr`, with its line."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            found.append((node.attr, node.lineno))
    return found


def main():
    if not DESIGN.is_dir():
        print('check_spec_ownership: design module not found, skipping')
        return 1

    problems = []
    doors_found = set()
    readers = 0

    for path in sorted(DESIGN.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        text = path.read_text(encoding='utf-8')
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            problems.append('%s: will not parse: %s'
                            % (path.relative_to(ROOT), exc.msg))
            continue
        lines = text.split('\n')

        for pair, lineno in chains(tree):
            if pair not in BANNED_CHAINS:
                continue
            problems.append(
                '%s:%s: reads %s.%s, which is EMPTY after the phase 7d '
                'migration -- use self.%s() instead'
                % (path.relative_to(ROOT), lineno, pair[0], pair[1],
                   DOORS[0] if pair[0] == 'profile_section_id' else DOORS[1]))

        for attr, lineno in plain_attrs(tree):
            if attr in DOORS:
                doors_found.add(attr)
                readers += 1
            if attr not in BANNED_ATTRS:
                continue
            source = lines[lineno - 1] if lineno <= len(lines) else ''
            # A comment explaining the legacy field is fine; a read is
            # not. The ast only sees code, so anything here is a read.
            problems.append(
                '%s:%s: uses the legacy ownership field .%s -- a line '
                'belongs to a Specification now (%s)'
                % (path.relative_to(ROOT), lineno, attr, source.strip()))

    missing = [door for door in DOORS if door not in doors_found]
    if missing:
        problems.append(
            'nothing calls %s -- either the accessor was renamed and this '
            'check is now watching nothing, or the readers went back to '
            'the legacy path' % ', '.join(missing))

    if problems:
        print("Specification ownership problems:")
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('%s read(s) of a window\'s parts, all through %s.'
          % (readers, ' / '.join(DOORS)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
