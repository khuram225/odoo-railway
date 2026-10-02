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

usage() {
    echo "usage: ci_check_health_route.sh <database> <path>=<status>[@<reason>] ..." >&2
    echo "  e.g. ci_check_health_route.sh aw_boot /aw/health/registry=200 \\" >&2
    echo "         '/aw/health=500@column .* does not exist'" >&2
    echo "  <reason> is a regex that must appear in the server log for a" >&2
    echo "  non-200; it defaults to 'does not exist in registry'." >&2
}

db=${1:-}
[ -n "$db" ] || { usage; exit 2; }
shift
[ "$#" -gt 0 ] || { usage; exit 2; }

# Several paths against ONE server start. The two routes have to be
# checked together -- the whole point of the split is that they disagree
# in the deploy-before-upgrade state, and that is only a meaningful
# assertion if both are asked of the same running build.
specs=$*

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

echo "--- starting odoo on $db, checking: $specs ---"
# `-d` IS the db_name setting (config.py declares it dest='db_name',
# type='comma'), and setting it is what lets an anonymous request resolve
# a database: _get_session_and_dbname falls back to the single database
# db_filter leaves, and db_filter filters by config['db_name']. Without
# it the request has no database, is served by the nodb routing map, and
# never reaches a module's controller at all -- a 404, not a verdict.
started_at=$(date +%s)
odoo -d "$db" \
    --addons-path="$addons" \
    --http-port="$port" --log-level=info >"$log" 2>&1 &
server=$!
echo "$server" > "$pidfile"

cleanup() {
    kill "$server" 2>/dev/null || true
    rm -f "$pidfile"
}

fail() {
    echo "::error::$1"
    echo "--- last response body ---"
    cat /tmp/health_body.txt 2>/dev/null || echo "(no body)"
    echo "--- last 80 lines of the odoo log ---"
    tail -80 "$log" 2>/dev/null || echo "(no log at $log)"
    cleanup
    exit 1
}

# Readiness, measured on the first path given. `curl` with no -m, because
# the socket is bound before the registry is loaded (ThreadedServer.run
# does http_spawn() then preload_registries, both under Registry._lock),
# so the FIRST request legitimately waits out the registry load.
first_path=${1%%=*}
ready=''
for _ in $(seq 1 90); do
    if curl -s -o /dev/null -w '%{http_code}' \
            "http://localhost:$port$first_path" >/tmp/health_code.txt 2>/dev/null
    then
        [ "$(cat /tmp/health_code.txt)" = "000" ] || { ready=1; break; }
    fi
    # A server that has exited is never going to answer; waiting out the
    # full timeout would just hide the reason.
    kill -0 "$server" 2>/dev/null || { echo "odoo exited before serving"; break; }
    sleep 2
done
[ -n "$ready" ] || fail "odoo never answered on port $port (no HTTP response at all)"

# ---------------------------------------------------------------------
# COLD START TO FIRST ANSWER. This, not per-request latency, is what
# Railway's healthcheckTimeout (300s in odoo/railway.json) is measured
# against: it polls a fresh container until one answer comes back.
#
# Reported because the question "is this well inside the timeout?"
# deserves a measurement rather than an opinion. Note what it is NOT:
# the ~63s "Registry loaded in" line in an INSTALL log is the whole
# `-i` run -- every module and every data file -- not a registry load on
# an installed database. Those are different numbers by two orders of
# magnitude, and confusing them is how a healthcheck timeout gets set by
# superstition.
# ---------------------------------------------------------------------
ready_after=$(( $(date +%s) - started_at ))
echo "--- first answer ${ready_after}s after start; server reports: $(
    grep -oE 'Registry loaded in [0-9.]+s' "$log" | head -1)"
echo "::notice::$db cold start to first HTTP answer: ${ready_after}s ($(
    grep -oE 'Registry loaded in [0-9.]+s' "$log" | head -1))"

for spec in "$@"; do
    path=${spec%%=*}
    rest=${spec#*=}
    expect=${rest%%@*}
    case "$rest" in
        *@*) reason=${rest#*@} ;;
        *)   reason='does not exist in registry' ;;
    esac

    # Each request is timed, because "well inside Railway's healthcheck
    # timeout" is a claim about seconds and has to be measured rather
    # than assumed.
    # Assigned, then OVERWRITTEN on failure -- never
    # `$(curl ... || echo ...)`, which concatenates curl's own output with
    # the fallback's. That is literally how an earlier version of this
    # reported a status of "000000".
    out=$(curl -s -o /tmp/health_body.txt -w '%{http_code} %{time_total}' \
          "http://localhost:$port$path" 2>/dev/null) || out='000 0'
    seconds=${out#* }
    code=${out%% *}
    body=$(tr '\n' ' ' < /tmp/health_body.txt 2>/dev/null | head -c 200 || true)

    echo "--- $path -> $code in ${seconds}s"
    [ "$code" = "$expect" ] \
        || fail "$path returned $code, expected $expect"

    # ---------------------------------------------------------------
    # The status code is not enough. BOTH directions can be right by
    # accident, and one of them already was: the route read
    # config['db_name'] -- a LIST in Odoo 19 -- and handed it to
    # Registry(), so it answered 500 on a perfectly healthy instance. A
    # step asserting only "500" would have called that a pass and
    # reported the gate verified. So each outcome must be right FOR THE
    # STATED REASON.
    # ---------------------------------------------------------------
    if [ "$expect" = "200" ]; then
        # Our route's own words. Anything else answering 200 -- a proxy,
        # a stray server, core's page under a redirect -- is not this
        # gate passing.
        case "$body" in
            pass:*) : ;;
            *) fail "$path: 200 did not come from this route; body: $body" ;;
        esac
    else
        grep -qE "$reason" "$log" \
            || fail "$path: got $code, but the log never matches '$reason',
so this failure has some other cause and the gate was not exercised"
    fi

    # Published as a ::notice:: ANNOTATION, which is the part readable
    # back without a token (/check-runs/<id>/annotations).
    # $GITHUB_STEP_SUMMARY was the first choice and was wrong: it renders
    # in the run's UI but never appears as the check run's
    # output.summary, so the evidence stayed as unreadable as before.
    # Single line -- a newline ends an annotation.
    echo "::notice::$path on $db: expected $expect, got $code in ${seconds}s -- $body"

    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        {
            echo "- \`$path\` on \`$db\`: expected $expect, got **$code**" \
                 "in ${seconds}s — \`$body\`"
            [ "$expect" = "200" ] || {
                echo "  - matched: \`$(grep -oE "$reason" "$log" | head -1)\`"; }
        } >> "$GITHUB_STEP_SUMMARY"
    fi
done

cleanup
echo "ok: every path answered as required"
