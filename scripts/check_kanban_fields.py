#!/usr/bin/env python3
"""Reject QWeb directives placed directly on a <field> in a kanban arch.

In a kanban card, <field> is not rendered as markup -- the web client
turns it into a Field COMPONENT and passes every attribute straight
through as `attrs`. A `t-else=""` on it therefore compiles to
`attrs: {'t-else':, ...}`, and the template dies at compile time with
OwlError "Unexpected token ','" the moment the view is opened.

Nothing else catches it. The XML is well-formed, load order is fine,
and `check_view_schemas.py` cannot help because Odoo ships no RelaxNG
for kanban -- it is validated by Python in core, which does not look at
this. So it fails only in the browser, for whoever opens the view
first.

The fix is always the same shape: wrap the field in the conditional
rather than putting the conditional on the field.

    <t t-if="record.picture.raw_value"><field name="picture" .../></t>
    <t t-else=""><field name="preview" .../></t>

Usage: python scripts/check_kanban_fields.py
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / 'odoo' / 'addons'

# t-att / t-attf are fine: they set an attribute value rather than
# controlling whether the element renders at all, and the Field
# component handles them.
BANNED = ('t-if', 't-elif', 't-else', 't-foreach', 't-as', 't-call')


def main():
    problems = []
    checked = 0

    for path in sorted(MODULES.rglob('*.xml')):
        try:
            tree = ET.parse(path)
        except ET.ParseError as error:
            problems.append('%s: not well-formed: %s'
                            % (path.relative_to(ROOT), error))
            continue
        for record in tree.getroot().iter('record'):
            if record.get('model') != 'ir.ui.view':
                continue
            arch = record.find("field[@name='arch']")
            if arch is None:
                continue
            for kanban in arch.iter('kanban'):
                checked += 1
                for field in kanban.iter('field'):
                    for attribute in field.attrib:
                        if attribute in BANNED:
                            problems.append(
                                "%s: view '%s' has %s on <field "
                                "name=\"%s\"> inside a kanban. Wrap the "
                                "field in <t %s=\"...\"> instead -- a "
                                "kanban <field> becomes a component and "
                                "the attribute is passed through as "
                                "attrs, which will not compile."
                                % (path.relative_to(ROOT), record.get('id'),
                                   attribute, field.get('name') or '?',
                                   attribute))

    if problems:
        print('Kanban <field> problems:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('%s kanban arch(es) put no QWeb directives directly on a '
          '<field>.' % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
