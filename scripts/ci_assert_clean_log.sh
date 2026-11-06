#!/bin/sh
# Fail if an Odoo install log contains an error.
#
# `--stop-after-init` is not a sufficient gate on its own: Odoo exits 0 for
# failures it only LOGS -- a data file that could not resolve a ref, a view
# that was stored but is invalid, a compute that raised while populating a
# column. Those are exactly the ones that reach production looking fine, so
# the log is read as well as the exit code.
#
# Usage: scripts/ci_assert_clean_log.sh /tmp/aw_boot.log
set -eu

log=${1:?usage: ci_assert_clean_log.sh <logfile>}
[ -f "$log" ] || { echo "FATAL: $log does not exist, so nothing was checked" >&2; exit 1; }

# Known-harmless lines. Each one is here with a reason, and the list is
# deliberately short: anything not named is a failure.
#
#   _sql_constraints   Odoo 19 dropped the attribute and only warns. Every
#                      such list in this repo is dead and converting them
#                      needs checking against live data first (CLAUDE.md).
#   Missing not-null   fires for a column being created on this very run.
ignore='Model attribute ._sql_constraints. is no longer supported|Missing not-null constraint'

found=$(grep -E ' (ERROR|CRITICAL) |Traceback \(most recent call last\)' "$log" \
        | grep -vE "$ignore" || true)

if [ -n "$found" ]; then
    echo "::error::the install logged errors -- the registry or a data file did not load"
    printf '%s\n' "$found"
    # The job log needs a signed-in user to read; annotations do not. Put
    # the first error line, and what follows it, where the check-runs API
    # shows them.
    first=$(printf '%s\n' "$found" | head -1 | cut -c1-400)
    echo "::error::first error line: $first"
    at=$(grep -n -m1 -F -- "$first" "$log" | cut -d: -f1 || true)
    if [ -n "$at" ]; then
        # A traceback ends in the line that says what went wrong: the
        # last unindented line before the next timestamped log line.
        exc=$(awk -v n="$at" 'NR > n { if ($0 ~ /^20[0-9][0-9]-[0-9][0-9]-/) exit; if ($0 !~ /^[[:space:]]/) last = $0 } END { print last }' "$log" | cut -c1-500)
        [ -n "$exc" ] && echo "::error::exception: $exc"
        next=$(sed -n "$((at + 1)),$((at + 3))p" "$log" | tr '\n' ' ' | cut -c1-400)
        echo "::error::after it: $next"
    fi
    exit 1
fi

# A log with no "Modules loaded." never finished installing, however
# quietly it exited.
if ! grep -q 'Modules loaded\.' "$log"; then
    echo "::error::the install never reached \"Modules loaded.\" -- it did not finish"
    tail -40 "$log"
    exit 1
fi

modules=$(grep -cE 'loading [0-9]+ modules|module [a-z0-9_]+: creating or updating' "$log" || true)
echo "ok: install log is clean ($(wc -l < "$log") lines)"

# Published as an annotation, which IS readable through the check-runs
# API without a token (the step summary is not -- it renders in the run's
# UI only). The module count is there because an install that loaded
# almost nothing and exited cleanly is the failure this repo keeps
# hitting: a green tick over code nothing read.
echo "::notice::$log clean: $(wc -l < "$log") lines, $modules module line(s), $(
    grep -oE 'Registry loaded in [0-9.]+s' "$log" | head -1)"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        echo "### install log \`$log\`: clean"
        echo
        echo "- $(wc -l < "$log") lines, $modules module-loading line(s)"
        echo "- reached: \`$(grep -o 'Modules loaded\.' "$log" | head -1)\`"
        echo "- registry: \`$(grep -oE 'Registry loaded in [0-9.]+s' "$log" | head -1)\`"
    } >> "$GITHUB_STEP_SUMMARY"
fi
