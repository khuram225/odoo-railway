#!/usr/bin/env python3
"""Every header field the configurator can WRITE must also be LOADED.

The bug this exists for: `manual_rate` was in CONFIGURATOR_HEADER_FIELDS
but not in get_configurator_data()'s header, so the client had no value
for it, sent nothing back, and save_layout wrote the nothing. A
hand-entered price override was destroyed by every single save, silently
-- no error, no log line, and nothing in the UI to notice, because the
field has no control in the configurator at all.

The asymmetry is the whole bug, and it only exists ACROSS the two ends
of one round trip, so neither the OWL checks nor anything server-side
can see it. Same shape as check_configurator_payload.py, one level down.

A field may legitimately be loaded but not writable -- window_series_name
is display-only -- so this is deliberately one-directional.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / 'odoo' / 'addons' / 'aw_fenestration_design'


def tuple_names(source, name):
    match = re.search(r'%s = \((.*?)\)' % name, source, re.S)
    if not match:
        return None
    return set(re.findall(r"'(\w+)'", match.group(1)))


def loaded_header_keys(source):
    """Keys of the dict under 'header' in get_configurator_data."""
    keys = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == 'header'
                    and isinstance(value, ast.Dict)):
                keys |= {k.value for k in value.keys
                         if isinstance(k, ast.Constant)}
    return keys


def main():
    source = (DESIGN / 'models' / 'design.py').read_text(encoding='utf-8')

    writable = tuple_names(source, 'CONFIGURATOR_HEADER_FIELDS')
    protected = tuple_names(source, 'CONFIGURATOR_PROTECTED_HEADER')
    if writable is None or protected is None:
        print('CONFIGURATOR_HEADER_FIELDS / '
              'CONFIGURATOR_PROTECTED_HEADER not found in design.py')
        return 1

    loaded = loaded_header_keys(source)
    problems = [
        "'%s' is writable by save_layout but never loaded, so every save "
        "blanks it" % name
        for name in sorted(writable - loaded)
    ]
    problems += [
        "'%s' is protected but not writable, so the protection is dead "
        "code" % name
        for name in sorted(protected - writable)
    ]

    if problems:
        print('Configurator header problems:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('All %s writable header field(s) are loaded; %s protected from '
          'being blanked by an unsent value.' % (len(writable),
                                                 len(protected)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
