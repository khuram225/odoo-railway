#!/usr/bin/env python3
"""Reject OWL template variables whose name OWL rewrites or reserves.

OWL's expression compiler substitutes a handful of words for operators
BEFORE parsing (owl.js's WORD_REPLACEMENT): and -> &&, or -> ||,
gt -> >, gte -> >=, lt -> <, lte -> <=. So a loop written as

    <t t-foreach="types" t-as="lt" t-key="lt.id">

compiles to `const key1 = <.id;` and dies at runtime with
OwlError "Unexpected token '<'". It has a separate RESERVED_WORDS list
(window, new, in, Math, ...) that breaks or shadows globals the same way.

This matters because nothing else catches it: the file is well-formed
XML, it loads server-side without complaint, and the failure only
appears in the browser when the component is first opened. That's
exactly how it reached production here once already.

Usage:
    python scripts/check_owl_names.py [file ...]

With no arguments, checks every *.xml file under a static/src directory
(OWL templates live there; server-side QWeb views are a different
compiler and are not affected).
"""
import re
import sys
from pathlib import Path

# owl.js: WORD_REPLACEMENT — silently rewritten into operators.
OWL_OPERATOR_WORDS = {'and', 'or', 'gt', 'gte', 'lt', 'lte'}

# owl.js: RESERVED_WORDS — not rewritten, but reserved or shadowing a
# global, and broken as a variable name in the same way.
OWL_RESERVED_WORDS = {
    'true', 'false', 'NaN', 'null', 'undefined', 'debugger', 'console',
    'window', 'in', 'instanceof', 'new', 'function', 'return', 'eval',
    'void', 'Math', 'RegExp', 'Array', 'Object', 'Date', '__globals__',
}

# t-as="x", t-set="x" — both introduce a name into the expression scope.
NAME_RE = re.compile(r'\bt-(?:as|set)\s*=\s*"([^"]*)"')

# Comments are stripped before scanning: nothing in them is compiled, and
# a comment explaining this very rule will quote the bad name verbatim.
COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)

# Selection state a template must not reach into directly. Selection is a
# PATH now, not (row, leaf), so `state.selected.row` silently read
# undefined for a panel (rendering "Row NaN") and threw outright for a
# divider, where it is null -- crashing the whole component on every
# re-render, including zoom.
#
# check_owl_getters.mjs CANNOT catch this: the expression lives in the
# template, not in a getter, so it passes cleanly on the broken code.
# Read selection only through selectionMode / selectedPanel /
# selectedPanelLabel / selectedPanelSize / selectedDividerEntry.
FORBIDDEN_STATE_RE = re.compile(r'\bstate\.(?:selected|selectedDivider)\b')

# owl.js compiles every SYMBOL in a template expression into a lookup on
# the component context UNLESS it is in its RESERVED_WORDS list. So a
# template calling parseInt() compiles to ctx['parseInt'](...), which is
# undefined, and the handler dies with "vNN is not a function" -- but
# only when the user actually interacts with the control, which is why
# neither the getter check nor anything else sees it.
#
# RESERVED_WORDS (so these DO work and must NOT be flagged -- a checker
# that cries wolf about Math.round gets ignored):
#   true false NaN null undefined debugger console window in instanceof
#   new function return eval void Math RegExp Array Object Date
#
# Everything else global is a trap. These are the ones actually reachable
# from a template.
UNSAFE_GLOBALS = (
    'parseInt', 'parseFloat', 'Number', 'String', 'Boolean', 'isNaN',
    'isFinite', 'JSON', 'Set', 'Map', 'Symbol', 'Promise', 'Error',
    'encodeURIComponent', 'decodeURIComponent', 'structuredClone',
)

# Only inside a t-* expression attribute, and only as a call or member
# access -- a plain word in ordinary text is not an expression.
EXPR_ATTR_RE = re.compile(r'\b(t-(?:att-[\w-]+|attf-[\w-]+|on-[\w.]+|if|elif'
                          r'|else|esc|out|set|value|foreach|key|props))\s*=\s*'
                          r'"([^"]*)"')
UNSAFE_CALL_RE = re.compile(
    r'(?<![.\w])(' + '|'.join(UNSAFE_GLOBALS) + r')\s*[.(]')

REPO_ROOT = Path(__file__).resolve().parent.parent


def check_file(path: Path) -> list[str]:
    problems = []
    raw = path.read_text(encoding='utf-8')
    # Blank out comments while preserving newlines, so line numbers stay true.
    text = COMMENT_RE.sub(
        lambda m: re.sub(r'[^\n]', ' ', m.group(0)), raw)
    for match in NAME_RE.finditer(text):
        name = match.group(1).strip()
        line = text.count('\n', 0, match.start()) + 1
        if name in OWL_OPERATOR_WORDS:
            problems.append(
                f'{path}:{line}: t-as/t-set="{name}" — OWL rewrites '
                f'"{name}" into an operator before parsing; rename it'
            )
        elif name in OWL_RESERVED_WORDS:
            problems.append(
                f'{path}:{line}: t-as/t-set="{name}" — reserved in OWL '
                f'expressions; rename it'
            )

    for attr_match in EXPR_ATTR_RE.finditer(text):
        attr, expression = attr_match.group(1), attr_match.group(2)
        for call in UNSAFE_CALL_RE.finditer(expression):
            line = text.count('\n', 0, attr_match.start()) + 1
            problems.append(
                f'{path}:{line}: {attr} calls the global {call.group(1)}() — '
                f'OWL resolves it against the component context, where it is '
                f'undefined, so this only fails when the control is used. '
                f'Move the conversion into a component method.'
            )

    for match in FORBIDDEN_STATE_RE.finditer(text):
        line = text.count('\n', 0, match.start()) + 1
        problems.append(
            f'{path}:{line}: reads {match.group(0)} directly — selection is '
            f'a path; go through selectionMode / selectedPanel / '
            f'selectedPanelLabel / selectedPanelSize / selectedDividerEntry'
        )
    return problems


def main(argv: list[str]) -> int:
    if argv:
        files = [Path(f) for f in argv]
    else:
        files = [
            f for f in REPO_ROOT.rglob('*.xml')
            if '.git' not in f.parts and 'static' in f.parts and 'src' in f.parts
        ]

    all_problems = []
    for f in files:
        if not f.is_file():
            continue
        all_problems.extend(check_file(f))

    if all_problems:
        print('OWL template problems:')
        for p in all_problems:
            print(f'  {p}')
        return 1
    print(f'No OWL template problems in {len(files)} file(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
