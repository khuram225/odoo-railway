#!/usr/bin/env bash
# Rehearse a deploy on a COPY of production before merging.
#
# Restores a dump of the live database into a scratch Postgres, runs the
# upgrade of the checked-out code on it (the same command the entrypoint
# runs), counts the rows the change touches, re-explodes every design to
# compare its cost and price with what is stored, and calls both health
# routes. Nothing here writes to production: the only thing taken from it is
# a read-only pg_dump.
#
# Needs: Docker, the Railway CLI logged in and linked to the project,
# pg_restore on the PATH (any Postgres client 16+), a clean-enough checkout
# of the branch you want to rehearse.
#
#   scripts/rehearse.sh              dump (if none is kept), restore, upgrade, compare
#   scripts/rehearse.sh --fresh      take a new dump even if one is kept
#   scripts/rehearse.sh --dump-only  just take the dump and check it
#   scripts/rehearse.sh --clean      delete the dump, the containers, the image
#
# THE DUMP IS CUSTOMER DATA. It lives in $REHEARSE_DIR (default
# ~/aw-rehearsal), never in the repository, and --clean removes it.
# Expect ~6.5 MB for a 91 MB database (custom format, compressed).
#
# Add the tables your change touches: REHEARSE_TABLES="aw_profile_position
# aw_vendor_alias" scripts/rehearse.sh  (counted before and after).
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
DIR=${REHEARSE_DIR:-$HOME/aw-rehearsal}
DUMP=$DIR/odoo.dump
NET=aw-rehearsal-net
PG=aw-rehearsal-pg
APP=aw-rehearsal-odoo
IMAGE=aw-rehearsal:latest
DB=rehearsal
DEFAULT_TABLES="aw_design aw_design_bom_line aw_window_template aw_profile_section_line aw_profile_position aw_profile_rate aw_glass_rate aw_vendor_rate_list aw_vendor_bar_length aw_cut_plan"
TABLES=${REHEARSE_TABLES:-$DEFAULT_TABLES}
# What the entrypoint upgrades; keep in step with odoo/entrypoint.sh.
MODULES=${ODOO_UPGRADE_MODULES:-aw_fenestration_core,aw_fenestration_design,aw_web_chatter_toggle}

say() { printf '\n== %s\n' "$*"; }
die() { printf 'REHEARSAL FAILED: %s\n' "$*" >&2; exit 1; }

clean() {
    docker rm -f "$APP" "$PG" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--clean" ]; then
    clean
    docker rmi "$IMAGE" >/dev/null 2>&1 || true
    rm -rf "$DIR"
    echo "removed containers, the image and $DIR (the dump)"
    exit 0
fi

# -- 0. what is there to work with ------------------------------------------
say "disk and tools"
mkdir -p "$DIR"
df -h "$DIR" | tail -1
free_gb=$(df -Pk "$DIR" | awk 'NR==2 {printf "%d", $4/1048576}')
[ "$free_gb" -ge 10 ] || die "less than 10 GB free on the disk holding $DIR"
command -v railway >/dev/null || die "the Railway CLI is not installed"
command -v pg_restore >/dev/null || die "pg_restore is not on the PATH"
echo "branch: $(git -C "$REPO" branch --show-current) @ $(git -C "$REPO" rev-parse --short HEAD)"

# -- 1. the dump -------------------------------------------------------------
if [ "${1:-}" = "--fresh" ] || [ ! -s "$DUMP" ]; then
    say "dumping production (read-only pg_dump over railway ssh)"
    # base64 so the binary survives the ssh terminal
    railway ssh -s odoo -- sh -c \
        'pg_dump -Fc -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" odoo | base64' \
        2>/dev/null | grep -E '^[A-Za-z0-9+/=]+$' | base64 -d > "$DUMP.part"
    mv "$DUMP.part" "$DUMP"
fi
pg_restore --list "$DUMP" >/dev/null || die "the dump does not read back; delete $DUMP and retry"
ls -l "$DUMP" | awk '{print "dump:", $5, "bytes"}'
[ "${1:-}" = "--dump-only" ] && { echo "dump kept in $DIR; delete with: scripts/rehearse.sh --clean"; exit 0; }

command -v docker >/dev/null || die "Docker is not installed (see the notes in CLAUDE.md, 'Rehearsal')"

# -- 2. scratch Postgres with the dump restored ------------------------------
say "scratch Postgres 16 with the dump restored"
clean
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=odoo \
    -e POSTGRES_PASSWORD=odoo -e POSTGRES_DB=postgres postgres:16 >/dev/null
until docker exec "$PG" pg_isready -U odoo >/dev/null 2>&1; do sleep 1; done
docker exec "$PG" createdb -U odoo "$DB"
docker cp "$DUMP" "$PG:/tmp/odoo.dump"
docker exec "$PG" pg_restore -U odoo -d "$DB" --no-owner --no-privileges /tmp/odoo.dump 2>&1 \
    | tail -3 || true

count() {
    for t in $TABLES; do
        n=$(docker exec "$PG" psql -U odoo -d "$DB" -Atc "select count(*) from $t" 2>/dev/null || echo "n/a")
        printf '%-28s %s\n' "$t" "$n"
    done
}
say "rows before"
count | tee "$DIR/before.txt"

# -- 3. the image of THIS code, then its upgrade -----------------------------
say "building the image from odoo/Dockerfile"
docker build -q -t "$IMAGE" -f "$REPO/odoo/Dockerfile" "$REPO/odoo" >/dev/null

ODOO_ENV=(-e HOST=$PG -e USER=odoo -e PASSWORD=odoo)
run_odoo() { docker run --rm --network "$NET" "${ODOO_ENV[@]}" "$IMAGE" "$@"; }

say "upgrade: odoo -u $MODULES --stop-after-init"
run_odoo odoo -d "$DB" --db_host="$PG" --db_user=odoo --db_password=odoo \
    -u "$MODULES" --stop-after-init --no-http --log-level=info \
    > "$DIR/upgrade.log" 2>&1 || { tail -40 "$DIR/upgrade.log"; die "the upgrade exited non-zero"; }
sh "$REPO/scripts/ci_assert_clean_log.sh" "$DIR/upgrade.log" || die "the upgrade logged errors (see $DIR/upgrade.log)"
echo "upgrade log is clean ($DIR/upgrade.log)"

say "rows after"
count | tee "$DIR/after.txt"
say "what changed"
diff "$DIR/before.txt" "$DIR/after.txt" && echo "(no row counts changed)" || true

# -- 4. every design re-exploded, compared with what is stored ---------------
say "re-exploding every design (rolled back)"
docker run --rm -i --network "$NET" "$IMAGE" odoo shell -d "$DB" \
    --db_host="$PG" --db_user=odoo --db_password=odoo --no-http \
    < "$REPO/scripts/rehearse_explode.py" 2>&1 | tee "$DIR/explode.log" | grep '^REHEARSAL' || true
grep -q '^REHEARSAL designs different 0' "$DIR/explode.log" \
    || die "a design costs or explodes differently after the upgrade (see $DIR/explode.log)"

# -- 5. the server starts and both health routes answer ----------------------
say "health routes"
docker run -d --name "$APP" --network "$NET" -p 18069:8069 "$IMAGE" \
    odoo -d "$DB" --db_host="$PG" --db_user=odoo --db_password=odoo \
    --without-demo=all --log-level=warn >/dev/null
for route in /aw/health/registry /aw/health; do
    code=000
    for _ in $(seq 1 60); do
        code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:18069$route" || true)
        [ "$code" = 200 ] && break
        sleep 2
    done
    echo "$route -> $code"
    [ "$code" = 200 ] || die "$route did not answer 200"
done
clean
say "REHEARSAL PASSED -- the upgrade of $(git -C "$REPO" rev-parse --short HEAD) ran clean on a copy of production"
echo "The dump is customer data. Delete it with: scripts/rehearse.sh --clean"
