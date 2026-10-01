#!/usr/bin/env python3
"""Catch undefined names and duplicate dict keys in our Python.

`python -m compileall` only checks SYNTAX. A name that is used but
never imported is perfectly valid syntax and explodes at import time --
and in Odoo that means the module fails to load and the whole instance
refuses to start.

That is not hypothetical: `@api.model` was added to glass_spec.py,
which imported only `fields, models`. Every check in this repo passed,
the deploy went out, and the container died with
"NameError: name 'api' is not defined ... Failed to initialize
database". The same run also found three duplicated dict keys, where a
patch had inserted the same line twice and the second silently won.

pyflakes is the right tool and is one import away. "Imported but
unused" is ignored: Odoo modules legitimately import things for their
side effects, and a warning nobody can act on is a warning everyone
learns to skip.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Every module in the repo, found rather than listed: a hardcoded list
# silently skips a new one and still prints "pass". `print_estimation`
# arrived with 28 files and was read by none of the scoped checks.
ADDONS = ROOT / 'odoo' / 'addons'
# At ANY depth: the tenancy split put the print modules two levels down,
# at addons_print/pp_print_core, and a one-level scan stopped seeing them
# the moment they moved.
TARGETS = ([manifest.parent for manifest in sorted(
                ADDONS.rglob('__manifest__.py'))]
           + [ROOT / 'scripts']) if ADDONS.is_dir() else [ROOT / 'scripts']

# Reported by pyflakes but not worth failing a commit over here.
IGNORED = (
    'imported but unused',
    'unable to detect undefined names',
    "redefinition of unused",
)


def main():
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        print('check_python_names: pyflakes not installed, skipping '
              '(pip install pyflakes to enable)')
        return 0

    paths = [str(path) for path in TARGETS if path.exists()]
    result = subprocess.run(
        [sys.executable, '-m', 'pyflakes', *paths],
        capture_output=True, text=True)

    problems = [
        line for line in (result.stdout or '').splitlines()
        if line.strip() and not any(skip in line for skip in IGNORED)
    ]
    if problems:
        print('Python name problems (these break module load, not just '
              'lint):')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('No undefined names or duplicate dict keys in %s tree(s).'
          % len(paths))
    return 0


if __name__ == '__main__':
    sys.exit(main())
