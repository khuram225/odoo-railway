#!/usr/bin/env python3
"""scripts/ci_assert_tests.sh reports skipped tests and guards their number.

Runs the REAL script on a synthetic Odoo log: two tests and one whole class
skip themselves. It must say "skipped: 3" with every name and reason, pass with no skips list,
pass when the list is exact, fail when a skip is not listed (a new one), and
fail when a listed skip no longer skips. Without this, the guard that is meant
to stop skips creeping up could itself be broken and say nothing.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'ci_assert_tests.sh'

LOG = """\
2026-11-21 10:00:00,000 1 INFO aw_test odoo.addons.aw_x.tests.test_a: skipped TestA.test_one : no pleated type
2026-11-21 10:00:00,001 1 INFO aw_test odoo.addons.aw_x.tests.test_b: skipped TestB.test_two : this window made a single profile
2026-11-21 10:00:00,002 1 INFO aw_test odoo.addons.aw_x.tests.test_c: skipped setUpClass (odoo.addons.aw_x.tests.test_c.TestC) : No profile with two finishes here
2026-11-21 10:00:01,000 1 INFO aw_test odoo.modules.loading: 0 failed, 0 error(s) of 10 tests when loading database 'aw_test'
"""


def run(log, failures, skips=None):
    args = ['sh', str(SCRIPT), str(log), str(failures)]
    if skips is not None:
        args.append(str(skips))
    done = subprocess.run(args, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def main():
    try:
        subprocess.run(['sh', '-c', 'true'], check=True)
    except (OSError, subprocess.CalledProcessError):
        print("skipping: no sh on this machine")
        return 0
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        log, failures, skips = tmp / 'log', tmp / 'f.txt', tmp / 's.txt'
        log.write_text(LOG)
        failures.write_text('# none\n')

        code, out = run(log, failures)
        if code != 0 or 'skipped: 3 skip(s) among 10' not in out:
            problems.append("no list: should pass and say 'skipped: 3 skip(s) among 10': %r" % out)
        for needle in ('TestA.test_one -- no pleated type',
                       'TestB.test_two -- this window made a single profile',
                       'setUpClass:TestC -- No profile with two finishes here'):
            if needle not in out:
                problems.append("the annotation lacks %r" % needle)

        skips.write_text('TestA.test_one  why\nTestB.test_two  why\nsetUpClass:TestC  why\n')
        code, out = run(log, failures, skips)
        if code != 0:
            problems.append("an exact list should pass: %r" % out)

        skips.write_text('TestA.test_one  why\n')
        code, out = run(log, failures, skips)
        if code == 0 or 'TestB.test_two' not in out or 'not in the known-skips' not in out:
            problems.append("a new skip should fail and be named: %r" % out)

        skips.write_text('TestA.test_one  w\nTestB.test_two  w\nsetUpClass:TestC  w\nTestC.test_gone  w\n')
        code, out = run(log, failures, skips)
        if code == 0 or 'TestC.test_gone' not in out or 'no longer skip' not in out:
            problems.append("a listed skip that no longer skips should fail: %r" % out)

        log.write_text(LOG.replace('skipped TestA', 'xx').replace(
            'skipped TestB', 'yy').replace('skipped setUpClass', 'zz'))
        skips.write_text('# nothing\n')
        code, out = run(log, failures, skips)
        if code != 0 or 'skipped: 0 skip(s) among 10' not in out:
            problems.append("no skips and an empty list should pass: %r" % out)
    if problems:
        print("FAIL: %d problem(s)" % len(problems))
        for line in problems:
            print("  -", line)
        return 1
    print("skipped-test report and guard: all cases behave")
    return 0


if __name__ == '__main__':
    sys.exit(main())
