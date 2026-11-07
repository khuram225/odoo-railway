#!/bin/sh
# Read an Odoo --test-enable log and fail unless tests really ran and none
# failed or errored.
#
# `--stop-after-init` exits 0 or 1 whatever the tests did, so the exit code is
# not the gate; the summary line Odoo prints is:
#     N failed, M error(s) of T tests when loading database 'db'
# A log with NO such line means no test ran (wrong tags, module not updated),
# which must not read as a pass.
#
# Every failing test is also written as a ::error:: annotation (name, then the
# exception that ended its traceback), because the job log needs a signed-in
# user to read and annotations do not. GitHub shows only 10 annotations per
# step, so they go out in chunks of 12 tests per annotation.
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
    list=$(mktemp)
    grep -E '(FAIL|ERROR): (setUpClass|[Tt]est)' "$log" \
        | sed -E 's/.*((FAIL|ERROR): .*)$/\1/' | cut -c1-200 | sort -u \
    | while IFS= read -r key; do
        n=$(grep -n -m1 -F -- "$key" "$log" | cut -d: -f1 || true)
        [ -n "$n" ] || continue
        # where in OUR tests it failed (file:line and that line of code), then
        # the exception that ended the traceback
        exc=$(awk -v n="$n" 'NR > n { if ($0 ~ /^20[0-9][0-9]-[0-9][0-9]-/) exit; if ($0 ~ /\/tests\/[A-Za-z0-9_]+\.py", line [0-9]+/) { f = $0; getline c; code = c } if ($0 ~ /aw_fenestration_[a-z]+\/(models|wizard|controllers)\/[A-Za-z0-9_]+\.py", line [0-9]+/) { g = $0; getline d; gcode = d } if ($0 !~ /^[[:space:]]/) last = $0 } END { gsub(/^[[:space:]]+/, "", code); gsub(/^[[:space:]]+/, "", gcode); sub(/.*\/tests\//, "", f); sub(/.*addons\//, "", g); print "[" f "] " code " <= [" g "] " gcode " => " last }' "$log" | cut -c1-640)
        echo "$key -- $exc"
    done > "$list"
    split -l 12 "$list" "$list.part."
    for part in "$list".part.*; do
        [ -f "$part" ] || continue
        printf '::error::%s\n' "$(awk '{printf "%s%%0A", $0}' "$part")"
    done
    echo "::error::$failed failed, $errors errored of $total tests"
    exit 1
fi
echo "all $total tests passed"
