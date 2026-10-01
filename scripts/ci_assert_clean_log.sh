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
    exit 1
fi

# A log with no "Modules loaded." never finished installing, however
# quietly it exited.
if ! grep -q 'Modules loaded\.' "$log"; then
    echo "::error::the install never reached \"Modules loaded.\" -- it did not finish"
    tail -40 "$log"
    exit 1
fi

echo "ok: install log is clean ($(wc -l < "$log") lines)"
