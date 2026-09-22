#!/usr/bin/env python3
"""Reject XML comments containing "--", which is illegal per the XML spec
(comments may not contain "--" anywhere except as part of the closing
"-->") and breaks well-formedness. Odoo's data-file loader has hit this
twice in this repo already -- this script exists so the third time is
caught before commit instead of after a failed deploy.

Usage:
    python scripts/check_xml_comments.py [file ...]

With no arguments, checks every *.xml file in the repo. Exits non-zero
and prints each offending file/line if any comment contains "--".
"""
import re
import sys
from pathlib import Path

COMMENT_RE = re.compile(r'<!--(.*?)-->', re.DOTALL)

REPO_ROOT = Path(__file__).resolve().parent.parent


def check_file(path: Path) -> list[str]:
    problems = []
    text = path.read_text(encoding='utf-8')
    for match in COMMENT_RE.finditer(text):
        content = match.group(1)
        if '--' in content:
            line = text.count('\n', 0, match.start()) + 1
            problems.append(f'{path}:{line}: comment contains "--"')
    return problems


def main(argv: list[str]) -> int:
    if argv:
        files = [Path(f) for f in argv]
    else:
        files = list(REPO_ROOT.rglob('*.xml'))
        files = [f for f in files if '.git' not in f.parts]

    all_problems = []
    for f in files:
        if not f.is_file():
            continue
        all_problems.extend(check_file(f))

    if all_problems:
        print('XML comments containing "--" (illegal, breaks well-formedness):')
        for p in all_problems:
            print(f'  {p}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
