#!/usr/bin/env python3
"""Reject `ir.actions.act_window` dicts built without a "views" key.

The web client's _preprocessAction does, unguarded:

    action.views = [...action.views.map((v) => [v[0], v[1]])];

so an act_window without `views` dies with
"TypeError: Cannot read properties of undefined (reading 'map')" before
the dialog even opens.

The subtlety that makes this easy to miss: an action returned from a
BUTTON goes through /web/dataset/call_button, whose controller runs
clean_action(), which calls generate_views() and fills `views` in from
`view_mode`. So the same dict works from a button and crashes when the
configurator fetches it with orm.call() -- that goes through
/web/dataset/call_kw, which does NOT clean the action. `Save as preset`
crashed for exactly that reason while `Add Position`, an identical
shape, worked.

Declaring `views` explicitly makes a dict safe on both paths, so this
requires it everywhere rather than trying to guess the call path.

Usage:
    python scripts/check_act_window_views.py [file ...]
"""
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDONS = REPO_ROOT / 'odoo' / 'addons'

ACT_WINDOW = 'ir.actions.act_window'


def check_python(path: Path) -> list[str]:
    """AST rather than regex: a dict literal spans lines and nests."""
    problems = []
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError as exc:
        return [f'{path}:{exc.lineno}: could not parse: {exc.msg}']

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {
            k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        is_act_window = any(
            isinstance(k, ast.Constant) and k.value == 'type'
            and isinstance(v, ast.Constant) and v.value == ACT_WINDOW
            for k, v in zip(node.keys, node.values)
        )
        if is_act_window and 'views' not in keys:
            problems.append(
                f'{path}:{node.lineno}: act_window dict has no "views" — '
                f'add e.g. \'views\': [(False, \'form\')], or doAction() '
                f'will crash on action.views.map()'
            )
    return problems


JS_ACT_WINDOW_RE = re.compile(
    r'type:\s*["\']ir\.actions\.act_window["\']')


def check_js(path: Path) -> list[str]:
    """Brace-matched scan: find the object literal holding the type key."""
    problems = []
    text = path.read_text(encoding='utf-8')
    for match in JS_ACT_WINDOW_RE.finditer(text):
        start = text.rfind('{', 0, match.start())
        if start == -1:
            continue
        depth, end = 0, None
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        literal = text[start:(end or len(text)) + 1]
        if not re.search(r'\bviews\s*:', literal):
            line = text.count('\n', 0, match.start()) + 1
            problems.append(
                f'{path}:{line}: act_window object has no "views" — '
                f'add e.g. views: [[false, "form"]], or doAction() will '
                f'crash on action.views.map()'
            )
    return problems


def main(argv):
    if argv:
        files = [Path(a) for a in argv]
    else:
        files = [
            f for f in ADDONS.rglob('*.py')
            if '__pycache__' not in f.parts
        ] + list(ADDONS.rglob('*.js'))

    problems = []
    for path in files:
        if not path.is_file():
            continue
        if path.suffix == '.py':
            problems.extend(check_python(path))
        elif path.suffix == '.js':
            problems.extend(check_js(path))

    if problems:
        print('act_window actions missing "views":')
        for problem in problems:
            print(f'  {problem}')
        return 1
    print(f'All act_window actions declare "views" ({len(files)} file(s)).')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
