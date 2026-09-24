#!/usr/bin/env python3
"""Validate every view arch against Odoo's OWN RelaxNG schemas.

This is the same validation the upgrade runs (`ir.ui.view._validate_view`
-> `validate_view_arch` -> the RNG files in
odoo/addons/base/rng/), so anything it rejects here would have failed
the Upgrade with `ParseError: Invalid view <name> definition`.

It exists because that ParseError is close to useless on its own: the
server log printed the file, the line and "View error context:
'-no context-'", and nothing about WHAT was wrong. The actual cause was
`expand="0"` on a search view's <group>, valid in older Odoo and
silently dropped from v19's schema. Running the schema locally prints
the real message ("Invalid attribute expand for element group") in a
second, against a source of truth that updates itself when odoo-src is
refreshed.

Needs `lxml` and the ../odoo-src reference clone. Skips cleanly (exit 0)
when either is missing, so a clone without them is not blocked from
committing -- this catches a whole class of bug, but it is not worth
making it a hard dependency of every commit.

Usage: python scripts/check_view_schemas.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ODOO_SRC = ROOT.parent / 'odoo-src'
RNG_DIR = ODOO_SRC / 'odoo' / 'addons' / 'base' / 'rng'
MODULES = ('aw_fenestration_core', 'aw_fenestration_design',
           'aluminum_inventory', 'hello_check')

# Root tag -> schema file. Only the view types Odoo ships an RNG for:
# form and kanban are validated by Python in core, not by a schema, so
# there is nothing to check them against here and claiming otherwise
# would be worse than skipping them.
SCHEMAS = {
    'search': 'search_view.rng',
    'list': 'list_view.rng',
    'graph': 'graph_view.rng',
    'pivot': 'pivot_view.rng',
    'calendar': 'calendar_view.rng',
    'activity': 'activity_view.rng',
}


def main():
    try:
        from lxml import etree
    except ImportError:
        print('check_view_schemas: lxml not installed, skipping '
              '(pip install lxml to enable)')
        return 0
    if not RNG_DIR.is_dir():
        print('check_view_schemas: ../odoo-src not found, skipping')
        return 0

    schemas = {}
    for tag, filename in SCHEMAS.items():
        path = RNG_DIR / filename
        if path.is_file():
            schemas[tag] = etree.RelaxNG(etree.parse(str(path)))

    problems = []
    checked = 0
    for module in MODULES:
        module_dir = ROOT / 'odoo' / 'addons' / module
        if not module_dir.is_dir():
            continue
        for path in sorted(module_dir.rglob('*.xml')):
            try:
                tree = etree.parse(str(path))
            except etree.XMLSyntaxError as error:
                problems.append('%s: not well-formed: %s'
                                % (path.relative_to(ROOT), error))
                continue
            for record in tree.getroot().iter('record'):
                if record.get('model') != 'ir.ui.view':
                    continue
                arch = record.find("field[@name='arch']")
                if arch is None:
                    continue
                for node in arch:
                    schema = schemas.get(node.tag)
                    if schema is None:
                        continue
                    checked += 1
                    if schema.validate(node):
                        continue
                    # An inherited view is a fragment (xpath/attribute
                    # edits), not a whole arch, so the schema
                    # legitimately rejects it. Only complain about
                    # standalone views.
                    if record.find("field[@name='inherit_id']") is not None:
                        checked -= 1
                        continue
                    messages = '; '.join(
                        error.message for error in schema.error_log)
                    problems.append(
                        "%s: view '%s' (<%s>) fails Odoo's schema: %s"
                        % (path.relative_to(ROOT), record.get('id'),
                           node.tag, messages))

    if problems:
        print("Views that would fail the Upgrade's own validation:")
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('%s view arch(es) valid against Odoo\'s RelaxNG schemas '
          '(%s type(s) checked).' % (checked, len(schemas)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
