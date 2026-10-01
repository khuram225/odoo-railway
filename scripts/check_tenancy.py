#!/usr/bin/env python3
"""Print and aluminum are separate tenants. Keep them that way.

Two things are checked, and they fail for different reasons.

**1. Isolation.** In implementation, print runs on its own Railway service
and its own database, loading only `addons_print`. That only works if
nothing under `addons_print` depends on an aluminum or shared module --
a single `aw_fenestration_core` in a `depends` list makes the print
service refuse to install, on a path where that module is not even
present. The reverse matters as much: an aluminum module that reached
for a print one would break the aluminum service the same way. Neither
is visible on the development instance, where one addons path holds
both and everything resolves.

**2. The tenancy switch itself.** `addons_path` and `db_name` come from
the environment so one image can serve both services, and the entrypoint
substitutes them into the rendered config. That substitution is shell,
so it is RUN here rather than read: the real `substitute()` function is
extracted from `entrypoint.sh` and applied to a copy of the real
`odoo.conf`, then the result is checked -- the right value, and exactly
one of each key, since configparser rejects a duplicate.

Running it rather than reading it is the whole point. `dbfilter`'s value
is `^print$`, which is full of characters that mean something to sed and
to grep, and reasoning about which of them survive two layers of shell
quoting is how this sort of code goes wrong quietly.

Skips cleanly where it cannot run: no `sh` on the box, no manifests.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / 'odoo' / 'addons'
PRINT_TREE = ADDONS / 'addons_print'
ENTRYPOINT = ROOT / 'odoo' / 'entrypoint.sh'
CONF = ROOT / 'odoo' / 'odoo.conf'

# Prefixes that identify each tenant's own modules. A module whose name
# starts with neither is core Odoo or a third party, and shared freely.
ALUMINUM_PREFIXES = ('aw_', 'aluminum_', 'core_')
PRINT_PREFIXES = ('pp_', 'print_')


def manifests(tree):
    """(module name, depends list, path) for every module under `tree`."""
    found = []
    if not tree.is_dir():
        return found
    for manifest in sorted(tree.rglob('__manifest__.py')):
        try:
            values = eval(  # noqa: S307 - our own manifest
                manifest.read_text(encoding='utf-8'),
                {'__builtins__': {}}, {})
        except Exception as exc:
            found.append((manifest.parent.name, None, manifest, str(exc)))
            continue
        found.append((manifest.parent.name, values.get('depends') or [],
                      manifest, None))
    return found


def check_isolation():
    problems = []
    print_modules = manifests(PRINT_TREE)

    # Aluminum is everything with a manifest that is NOT under the print
    # tree -- discovered, not listed, so a new module is covered the day
    # it appears.
    aluminum_modules = [
        entry for entry in manifests(ADDONS)
        if PRINT_TREE not in entry[2].parents
    ]

    for name, depends, path, error in print_modules:
        if error:
            problems.append('%s: manifest will not parse: %s'
                            % (path.relative_to(ROOT), error))
            continue
        for dependency in depends:
            if dependency.startswith(ALUMINUM_PREFIXES):
                problems.append(
                    "%s: '%s' depends on '%s'. The print service loads ONLY "
                    "addons_print, so that module is not on its path and the "
                    "install fails there while working in development."
                    % (path.relative_to(ROOT), name, dependency))

    for name, depends, path, error in aluminum_modules:
        if error:
            problems.append('%s: manifest will not parse: %s'
                            % (path.relative_to(ROOT), error))
            continue
        for dependency in depends:
            if dependency.startswith(PRINT_PREFIXES):
                problems.append(
                    "%s: '%s' depends on '%s', which lives in addons_print. "
                    "The aluminum service does not load that tree."
                    % (path.relative_to(ROOT), name, dependency))

    return problems, len(print_modules), len(aluminum_modules)


def extract_substitute():
    """The real substitute() function out of entrypoint.sh."""
    if not ENTRYPOINT.is_file():
        return None
    text = ENTRYPOINT.read_text(encoding='utf-8')
    match = re.search(r'^substitute\(\) \{.*?^\}', text, re.S | re.M)
    return match.group(0) if match else None


def check_switch():
    """Run the entrypoint's own substitution against the real config."""
    problems = []
    body = extract_substitute()
    if body is None:
        return ["entrypoint.sh has no substitute() function, so the tenancy "
                "switch is not where this check thinks it is"]
    if not shutil.which('sh'):
        return []
    if not CONF.is_file():
        return ['odoo/odoo.conf not found']

    with tempfile.TemporaryDirectory() as tmp:
        rendered = Path(tmp) / 'odoo.conf'
        rendered.write_text(CONF.read_text(encoding='utf-8'), encoding='utf-8')
        # The function writes to /etc/odoo/odoo.conf; point it at the copy.
        # as_posix(): on Windows this runs under Git Bash, and a path
        # with backslashes is eaten by the shell before sed sees it.
        script = body.replace(
            '/etc/odoo/odoo.conf', rendered.as_posix()) + """
set -eu
substitute addons_path "/mnt/extra-addons/addons_print"
substitute db_name "print"
substitute dbfilter "^print\\$"
"""
        result = subprocess.run(['sh', '-c', script],
                                capture_output=True, text=True)
        if result.returncode != 0:
            problems.append(
                'the entrypoint\'s substitute() failed on a real config: %s'
                % (result.stderr.strip() or result.stdout.strip()))
            return problems

        text = rendered.read_text(encoding='utf-8')
        expected = {
            'addons_path': '/mnt/extra-addons/addons_print',
            'db_name': 'print',
            'dbfilter': '^print$',
        }
        for key, value in expected.items():
            line = '%s = %s' % (key, value)
            if line not in text:
                problems.append(
                    'substituting %s did not produce "%s"' % (key, line))
            # Exactly one: configparser rejects a duplicate key, so an
            # appended second line would abort the boot.
            count = len(re.findall(r'^%s\s*=' % re.escape(key), text, re.M))
            if count != 1:
                problems.append(
                    '%s appears %s times in the rendered config; configparser '
                    'rejects a duplicate key' % (key, count))
    return problems


def main():
    if not ADDONS.is_dir():
        print('check_tenancy: no addons directory, skipping')
        return 0

    problems, print_count, aluminum_count = check_isolation()
    problems.extend(check_switch())

    if problems:
        print('Tenancy problems:')
        for problem in problems:
            print('  %s' % problem)
        return 1

    print('%s print module(s) and %s aluminum module(s) stay on their own '
          'side; the tenancy switch substitutes cleanly.'
          % (print_count, aluminum_count))
    return 0


if __name__ == '__main__':
    sys.exit(main())
