#!/bin/sh
# Read an Odoo --test-enable log and decide whether the tests pass.
#
# `--stop-after-init` exits 0 or 1 whatever the tests did, so the exit code is
# not the gate; the summary line Odoo prints is:
#     N failed, M error(s) of T tests when loading database 'db'
# A log with NO such line means no test ran (wrong tags, module not updated),
# which must not read as a pass.
#
# KNOWN FAILURES. An optional second argument is a file of failures that are
# known and agreed (tests/known_failures.txt): one per line, the first word is
# the key, the rest is a note (area; TEST BUG or CODE BUG; why). The run
# FAILS when
#   - a test fails that is not listed        (a new break), or
#   - a listed test no longer fails          (so the list can only shrink).
# A key is Class.test_name, or setUpClass:Class for a class whose setUp
# failed (none of its tests ran).
#
# Every failing test is also written as a ::error:: annotation (name, where in
# our tests, the addon frame, the exception), because the job log needs a
# signed-in user to read and annotations do not. GitHub shows only 10
# annotations per step, so they go out in chunks of 12 tests per annotation.
#
# Usage: scripts/ci_assert_tests.sh /tmp/tests.log [known_failures.txt]
set -eu

log=${1:?usage: ci_assert_tests.sh <logfile> [known_failures.txt]}
known=${2:-}
[ -f "$log" ] || { echo "FATAL: $log does not exist, so nothing was checked" >&2; exit 1; }
if [ -n "$known" ] && [ ! -f "$known" ]; then
    echo "FATAL: $known does not exist" >&2
    exit 1
fi

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

work=$(mktemp -d)

# the key of every failing test, as the known-failures file spells it
grep -E '(FAIL|ERROR): ([A-Za-z0-9_]+[.][A-Za-z0-9_]+|setUpClass)' "$log" \
    | sed -E 's/.*(FAIL|ERROR): (.*)$/\2/' \
    | sed -E 's/^setUpClass \([A-Za-z0-9_.]*\.([A-Za-z0-9_]+)\).*/setUpClass:\1/' \
    | awk '{print $1}' | sort -u > "$work/failing" || true

if [ -n "$known" ]; then
    grep -vE '^[[:space:]]*(#|$)' "$known" | awk '{print $1}' | sort -u > "$work/listed"
else
    : > "$work/listed"
fi

# Every failure must have been recognised: a test class whose name the pattern
# above does not know would otherwise slip through (it did, in a probe).
found=$(wc -l < "$work/failing" | tr -d ' ')
if [ "$found" -ne $((failed + errors)) ]; then
    echo "::error::the summary says $((failed + errors)) failure(s) but $found were recognised in the log -- the gate cannot tell which one is new"
    exit 1
fi

comm -23 "$work/failing" "$work/listed" > "$work/new"       # failing, not listed
comm -13 "$work/failing" "$work/listed" > "$work/stale"     # listed, not failing

# annotate the new failures (all of them when there is no known list)
if [ -s "$work/new" ]; then
    : > "$work/lines"
    while IFS= read -r key; do
        case "$key" in
            setUpClass:*) pattern="setUpClass (.*[.]${key#setUpClass:})" ;;
            *) pattern="(FAIL|ERROR): $key" ;;
        esac
        n=$(grep -n -m1 -E -- "$pattern" "$log" | cut -d: -f1 || true)
        [ -n "$n" ] || { echo "$key -- (not found in the log)" >> "$work/lines"; continue; }
        # where in OUR tests it failed (file:line and that line of code), the
        # addon frame under it, then the exception that ended the traceback
        exc=$(awk -v n="$n" 'NR > n { if ($0 ~ /^20[0-9][0-9]-[0-9][0-9]-/) exit; if ($0 ~ /\/tests\/[A-Za-z0-9_]+\.py", line [0-9]+/) { f = $0; getline c; code = c } if ($0 ~ /aw_fenestration_[a-z]+\/(models|wizard|controllers)\/[A-Za-z0-9_]+\.py", line [0-9]+/) { g = $0; getline d; gcode = d } if ($0 ~ /^[A-Za-z_.]*(Error|Exception)/) { last = $0; more = 5 } else if (more > 0) { gsub(/^[[:space:]]+/, "", $0); last = last " | " $0; more-- } else if ($0 !~ /^[[:space:]]/) last = $0 } END { gsub(/^[[:space:]]+/, "", code); gsub(/^[[:space:]]+/, "", gcode); sub(/.*\/tests\//, "", f); sub(/.*addons\//, "", g); print "[" f "] " code " <= [" g "] " gcode " => " last }' "$log" | cut -c1-1800)
        echo "$key -- $exc" >> "$work/lines"
    done < "$work/new"
    split -l 12 "$work/lines" "$work/part."
    for part in "$work"/part.*; do
        [ -f "$part" ] || continue
        printf '::error::%s\n' "$(awk '{printf "%s%%0A", $0}' "$part")"
    done
fi

bad=0
if [ -s "$work/new" ]; then
    echo "::error::$(wc -l < "$work/new" | tr -d ' ') test(s) failed that are not in the known-failures list"
    bad=1
fi
if [ -s "$work/stale" ]; then
    echo "::error::$(wc -l < "$work/stale" | tr -d ' ') listed failure(s) now pass or no longer exist -- remove them from $known: $(tr '\n' ' ' < "$work/stale" | cut -c1-1500)"
    bad=1
fi
if [ "$bad" -ne 0 ]; then
    echo "::error::$failed failed, $errors errored of $total tests"
    exit 1
fi

listed=$(wc -l < "$work/listed" | tr -d ' ')
if [ "$listed" -gt 0 ]; then
    echo "::notice::$listed known failure(s) still failing, none new; $((total - failed - errors)) of $total tests pass"
else
    echo "all $total tests passed"
fi
