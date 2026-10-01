#!/bin/sh
# Start a real Odoo against an already-installed database and assert what
# /aw/health answers.
#
# Usage: scripts/ci_check_health_route.sh <database> <expected status>
#
#   ci_check_health_route.sh aw_boot 200   # a healthy build
#   ci_check_health_route.sh aw_boot 500   # after breaking the registry
#
# Why this is a script and not inline YAML: the first version was inline,
# hid the server's own log behind --log-level=warn, and reported
# "/aw/health returned 000000 on a healthy build" -- a status that is not
# a status (curl printed 000 for "could not connect" AND a `|| echo 000`
# fallback fired), with nothing on screen to say whether Odoo had died at
# startup or simply had not finished loading. A gate whose failure cannot
# be diagnosed is barely a gate, and that one was ALSO failing on good
# code, which quietly made the whole run meaningless: red on main and red
# on a deliberately broken branch prove nothing when compared.
#
# So: the server log goes to a file and is PRINTED on any failure, the
# wait is long enough for a cold registry over ~500 imported products,
# and "could not connect" is reported as exactly that rather than as a
# made-up HTTP code.
set -eu

db=${1:?usage: ci_check_health_route.sh <database> <expected status>}
expect=${2:?usage: ci_check_health_route.sh <database> <expected status>}

log=/tmp/odoo_http_${db}.log
addons=/usr/lib/python3/dist-packages/odoo/addons,odoo/addons
port=8069

# This script starts and KILLS an Odoo on a port and is meant to run in
# a throwaway container. Pointed at a workstation it finds the developer's
# own Odoo on that port instead -- which is how the first version of this
# was accidentally run, reporting a 404 from a local instance as though it
# were a verdict about this branch.
if [ "${CI:-}" = "" ] && [ "${AW_HEALTH_ALLOW_LOCAL:-}" != "1" ]; then
    echo "refusing to run outside CI: this starts and kills an Odoo on port" >&2
    echo "$port. Set AW_HEALTH_ALLOW_LOCAL=1 if that is really what you want." >&2
    exit 2
fi

# Is anything answering on the port? Decided by curl's EXIT CODE, not by
# whether a response arrived in time: exit 7 is "could not connect", which
# is the only thing that means free. The first version used `-m 2` and
# treated any failure as free, so a live server that was merely slow to
# render -- a website 404 page, say -- read as an empty port, and the run
# went on to test against a server it did not start.
port_is_open() {
    # Captured into a variable rather than tested with `&&`, so `set -e`
    # cannot turn a non-zero curl into an exit from the whole script.
    probe=0
    curl -s -o /dev/null -m 15 "http://localhost:$port/aw/health" || probe=$?
    [ "$probe" = "7" ] && return 1
    return 0  # answered, or timed out: either way something is listening
}

# A server left over from an earlier call in the same job would answer
# the next one -- from the code as it was BEFORE the break was injected,
# reporting a pass for a build it never loaded. That is the single most
# dangerous way this script could lie, so the port is confirmed dead
# rather than assumed.
#
# Done with a pid file and curl, not pkill/pgrep: those live in procps,
# which the odoo image is not required to carry, and a `|| true` around a
# missing command would silently skip the check entirely.
pidfile=/tmp/odoo_health_$port.pid
if [ -f "$pidfile" ]; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
fi
for _ in 1 2 3 4 5 6 7 8 9 10; do
    port_is_open || break
    sleep 2
done
if port_is_open; then
    echo "::error::something is already serving port $port; this run would" \
         "have tested that server instead of this build" >&2
    exit 1
fi

echo "--- starting odoo on $db (expecting /aw/health -> $expect) ---"
# `-d` IS the db_name setting (config.py declares it dest='db_name',
# type='comma'), and setting it is what lets an anonymous request resolve
# a database: _get_session_and_dbname falls back to the single database
# db_filter leaves, and db_filter filters by config['db_name']. Without
# it the request has no database, is served by the nodb routing map, and
# never reaches a module's controller at all -- a 404, not a verdict.
odoo -d "$db" \
    --addons-path="$addons" \
    --http-port="$port" --log-level=info >"$log" 2>&1 &
server=$!
echo "$server" > "$pidfile"

code=''
for _ in $(seq 1 90); do
    # -o writes the body, -w prints ONLY the status. No `|| echo`: a
    # failed connection must look like a failed connection.
    if curl -s -o /tmp/health_body.txt -w '%{http_code}' \
            "http://localhost:$port/aw/health" >/tmp/health_code.txt 2>/dev/null
    then
        code=$(cat /tmp/health_code.txt)
        [ "$code" = "000" ] || break
        code=''
    fi
    # A server that has exited is never going to answer; waiting out the
    # full timeout would just hide the reason.
    kill -0 "$server" 2>/dev/null || { echo "odoo exited before serving"; break; }
    sleep 2
done

fail() {
    echo "::error::$1"
    echo "--- /aw/health body ---"
    cat /tmp/health_body.txt 2>/dev/null || echo "(no body)"
    echo "--- last 80 lines of the odoo log ---"
    tail -80 "$log" 2>/dev/null || echo "(no log at $log)"
    kill "$server" 2>/dev/null || true
    rm -f "$pidfile"
    exit 1
}

[ -n "$code" ] || fail "odoo never answered on port $port (no HTTP response at all)"

echo "status=$code"
echo "body: $(cat /tmp/health_body.txt 2>/dev/null)"

if [ "$code" != "$expect" ]; then
    fail "/aw/health returned $code, expected $expect"
fi

# The log is worth showing on a PASS too when the pass is a 500: it is
# the only place the reason for that 500 is recorded, and the reason is
# the thing being verified.
if [ "$expect" = "500" ]; then
    echo "--- the failure this 500 reports ---"
    grep -E 'aw health check FAILED|does not exist in registry|Traceback' "$log" \
        | head -20 || echo "(nothing matched in the log)"
fi

kill "$server" 2>/dev/null || true
rm -f "$pidfile"
echo "ok: /aw/health returned $expect as required"
