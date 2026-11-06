#!/bin/sh
# Read an Odoo --test-enable log and fail unless tests really ran and none
# failed or errored.
#
# `--stop-after-init` exits 0 whatever the tests did, so the exit code is not
# the gate; the summary line Odoo prints is:
#     N failed, M error(s) of T tests when loading database 'db'
# A log with NO such line means no test ran (wrong tags, module not updated),
# which must not read as a pass.
#
# Every failing test is also written as a ::error:: annotation (name, then the
# exception that ended its traceback), because the job log needs a signed-in
# user to read and annotations do not.
#
# Usage: scripts/ci_assert_tests.sh /tmp/tests.log
set -eu

log=${1:?usage: ci_assert_tests.sh <logfile>}
[ -f "$log" ] || { echo "FATAL: $log does not exist, so nothing was checked" >&2; exit 1; }

summary=$(grep -E '[0-9]+ failed, [0-9]+ error\(s\) of [0-9]+ tests' "$log" | tail -1 || true)
if [ -z "$summary" ]; then
    echo "::error::no test summary in the log -- no test ran, so nothing was checked"
    exit 1
fi
failed=$(printf '%s\n' "$summary" | sed -E 's/.*[^0-9]([0-9]+) failed, .*/\1/')
errors=$(printf '%s\n' "$summary" | sed -E 's/.*failed, ([0-9]+) error.*/\1/')
total=$(printf '%s\n' "$summary" | sed -E 's/.* of ([0-9]+) tests.*/\1/')
echo "::notice::tests: $total ran, $failed failed, $errors errored"

if [ "$total" -eq 0 ]; then
    echo "::error::0 tests ran"
    exit 1
fi

if [ "$failed" -gt 0 ] || [ "$errors" -gt 0 ]; then
    # one annotation per failing test, capped so the list stays readable
    grep -E '(FAIL|ERROR): (Test|test)[A-Za-z0-9_.]*' "$log" \
        | sed -E 's/.*((FAIL|ERROR): [A-Za-z0-9_.]+).*/\1/' | sort -u | head -60 \
    | while read -r kind name; do
        n=$(grep -n -m1 -F "$kind $name" "$log" | cut -d: -f1 || true)
        [ -n "$n" ] || continue
        exc=$(awk -v n="$n" 'NR > n { if ($0 ~ /^20[0-9][0-9]-[0-9][0-9]-/) exit; if ($0 !~ /^[[:space:]]/) last = $0 } END { print last }' "$log" | cut -c1-300)
        echo "::error::$kind $name -- $exc"
    done
    echo "::error::$failed failed, $errors errored of $total tests"
    exit 1
fi
echo "all $total tests passed"
