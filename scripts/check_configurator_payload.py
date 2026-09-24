#!/usr/bin/env python3
"""Every payload key the configurator reads must be one the server sends.

The bug this exists for: `_attachment_catalogue()` was spread into
`get_series_context` but NOT into `get_configurator_data`, which is what
the configurator actually loads. So `state.data.mesh_types`,
`infill_types`, `glass_specs` and `grid_patterns` were all undefined on
open — the Mesh and Infill headings rendered with nothing underneath and
the glass override said "no Glass Specs exist yet", none of which looked
like a payload problem.

Nothing caught it. The OWL checks all run against the component, where
`this.state.data.mesh_types || []` is perfectly valid JavaScript that
quietly yields an empty list. The mismatch only exists ACROSS the two
files, so it needs a check that reads both.

This parses the Python with `ast` (following `**self._method()` spreads
one level) and greps the JS for `state.data.<key>`, then reports keys
read but never provided.

Usage:
    python scripts/check_configurator_payload.py
"""
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN = REPO_ROOT / 'odoo' / 'addons' / 'aw_fenestration_design'

MODEL = DESIGN / 'models' / 'design.py'
CLIENT = (DESIGN / 'static' / 'src' / 'design_configurator'
          / 'design_configurator.js')
TEMPLATE = (DESIGN / 'static' / 'src' / 'design_configurator'
            / 'design_configurator.xml')

LOADER = 'get_configurator_data'

# Set by the client itself rather than received from the server.
CLIENT_OWNED = set()


def _dict_keys(node, methods, seen=None):
    """Top-level string keys of a returned dict, following ** spreads."""
    seen = seen or set()
    keys = set()
    if not isinstance(node, ast.Dict):
        return keys
    for key, value in zip(node.keys, node.values):
        if key is None:
            # **something
            if (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr not in seen):
                seen.add(value.func.attr)
                keys |= _method_keys(methods, value.func.attr, seen)
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
    return keys


def _method_keys(methods, name, seen=None):
    """Keys of the dict a method returns."""
    func = methods.get(name)
    if not func:
        return set()
    keys = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            keys |= _dict_keys(node.value, methods, seen)
    return keys


def server_keys():
    tree = ast.parse(MODEL.read_text(encoding='utf-8'))
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if LOADER not in methods:
        return None, f'{MODEL}: no {LOADER}() found'
    return _method_keys(methods, LOADER), None


def client_keys():
    keys = set()
    pattern = re.compile(r'state\.data(?:\?)?\.([A-Za-z_$][\w$]*)')
    for path in (CLIENT, TEMPLATE):
        for match in pattern.finditer(path.read_text(encoding='utf-8')):
            keys.add(match.group(1))
    return keys


def main():
    provided, error = server_keys()
    if error:
        print(error)
        return 1

    read = client_keys()
    missing = sorted(read - provided - CLIENT_OWNED)

    if missing:
        print(f'The configurator reads payload keys {LOADER}() never sends:')
        for key in missing:
            print(f'  state.data.{key}')
        print('\nEither add them to the returned dict (or to a method it '
              'spreads with **), or stop reading them.')
        return 1

    print(f'{LOADER}() provides all {len(read)} payload key(s) the '
          f'configurator reads.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
