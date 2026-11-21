#!/usr/bin/env python3
"""Every tests/test_*.py must be imported by its tests/__init__.py.

Odoo finds an addon's tests only through that import. A test file that is not
imported does not fail: it simply never runs, and the job stays green. That
happened to test_piece_adjust.py (14 tests): CI said 492 tests before and 492
after, because the new file was not in __init__.py. Nothing said so.

Reads each addon's tests/__init__.py with ast (`from . import x`) and lists
the test files it does not import.
"""
import ast
import sys
from pathlib import Path

ADDONS = Path(__file__).resolve().parent.parent / 'odoo' / 'addons'


def imported(init):
    tree = ast.parse(init.read_text(encoding='utf-8'))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 \
                and node.module is None:
            names.update(alias.name for alias in node.names)
    return names


def missing(base=ADDONS):
    found, checked = [], 0
    for tests in sorted(base.glob('*/tests')):
        init = tests / '__init__.py'
        files = sorted(tests.glob('test_*.py'))
        if not files:
            continue
        if not init.is_file():
            found.append("%s has test files but no __init__.py" % tests)
            continue
        names = imported(init)
        for path in files:
            checked += 1
            if path.stem not in names:
                found.append("%s is not imported by %s, so its tests "
                             "never run" % (path.relative_to(base), init.name))
    return found, checked


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tests = Path(tmp) / 'demo' / 'tests'
        tests.mkdir(parents=True)
        (tests / 'test_a.py').write_text('')
        (tests / 'test_b.py').write_text('')
        (tests / '__init__.py').write_text('from . import test_a\n')
        wrong, _n = missing(Path(tmp))
        (tests / '__init__.py').write_text(
            'from . import test_a\nfrom . import test_b\n')
        right, _n = missing(Path(tmp))
    return wrong, right


def main():
    wrong, right = self_test()
    if len(wrong) != 1 or 'test_b' not in wrong[0] or right:
        print("FAIL: the self-test of this check is wrong: %r / %r"
              % (wrong, right))
        return 1
    found, checked = missing()
    if not checked:
        print("FAIL: found no test files under %s" % ADDONS)
        return 1
    if found:
        print("FAIL: test files that never run:")
        for line in found:
            print("  - " + line)
        return 1
    print("tests imported: all %d test file(s) are imported by their "
          "tests/__init__.py" % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
