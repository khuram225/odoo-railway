#!/bin/sh
# Railway entrypoint for Odoo 19.
#
# Runs as root only long enough to bootstrap the database role, fix volume
# ownership and render the config, then hands the process to the image's own
# unprivileged `odoo` user.
set -eu

: "${ODOO_ADMIN_PASSWD:?ODOO_ADMIN_PASSWD is required (master password for the database manager)}"

# Odoo 19 aborts at startup if the database role is literally named 'postgres'
# (odoo/cli/server.py: "Using the database user 'postgres' is a security risk").
# Railway's managed PostgreSQL hands out exactly that user, so fail loudly here
# instead of leaving a container that exits 1 on every boot.
if [ "${PGUSER:-}" = "postgres" ]; then
    echo "FATAL: PGUSER is 'postgres'. Odoo refuses to run as that role." >&2
    echo "       Use a scoped role, e.g. PGUSER=odoo, and set" >&2
    echo "       BOOTSTRAP_DATABASE_URL so this entrypoint can create it." >&2
    exit 1
fi

# --- Bootstrap the scoped role ------------------------------------------------
#
# A one-click deploy has no opportunity to run SQL by hand, and Odoo cannot use
# Railway's `postgres` superuser (above). So when BOOTSTRAP_DATABASE_URL is
# provided -- point it at ${{Postgres.DATABASE_URL}} -- create the least-
# privilege role Odoo actually connects as.
#
# CREATEDB is required: Odoo uses it to create, duplicate and restore
# databases, and to bootstrap the database named by db_name on first boot.
# NOSUPERUSER is the point of the exercise.
#
# Idempotent: ALTER on later boots keeps the password in step with PGPASSWORD,
# so rotating the variable is enough. Safe to leave set; safe to remove after
# the first successful boot if you would rather the app never hold superuser
# credentials.
if [ -n "${BOOTSTRAP_DATABASE_URL:-}" ]; then
    : "${PGUSER:?PGUSER is required when BOOTSTRAP_DATABASE_URL is set}"
    : "${PGPASSWORD:?PGPASSWORD is required when BOOTSTRAP_DATABASE_URL is set}"

    echo "bootstrap: waiting for PostgreSQL"
    i=0
    until psql "$BOOTSTRAP_DATABASE_URL" -tAc 'SELECT 1' >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -ge 30 ]; then
            echo "FATAL: could not reach PostgreSQL via BOOTSTRAP_DATABASE_URL after 60s" >&2
            exit 1
        fi
        sleep 2
    done

    # Double any single quotes so an awkward generated password cannot break
    # out of the SQL string literal.
    esc_user=$(printf '%s' "$PGUSER" | sed "s/'/''/g")
    esc_pass=$(printf '%s' "$PGPASSWORD" | sed "s/'/''/g")

    echo "bootstrap: ensuring role '$PGUSER' exists (LOGIN CREATEDB NOSUPERUSER)"
    psql "$BOOTSTRAP_DATABASE_URL" -v ON_ERROR_STOP=1 -q <<SQL
DO \$bootstrap\$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$esc_user') THEN
        ALTER ROLE "$esc_user" WITH LOGIN CREATEDB NOSUPERUSER NOCREATEROLE
            NOREPLICATION PASSWORD '$esc_pass';
    ELSE
        CREATE ROLE "$esc_user" WITH LOGIN CREATEDB NOSUPERUSER NOCREATEROLE
            NOREPLICATION PASSWORD '$esc_pass';
    END IF;
END
\$bootstrap\$;
SQL
    echo "bootstrap: role '$PGUSER' ready"
else
    echo "bootstrap: BOOTSTRAP_DATABASE_URL not set, assuming role '$PGUSER' already exists"
fi

# --- Filesystem ---------------------------------------------------------------

# Railway mounts volumes root-owned, and the upstream image never chowns them.
mkdir -p /var/lib/odoo /mnt/extra-addons

# admin_passwd is the only secret in odoo.conf, so it is appended here rather
# than committed. It stays in the [options] section because the committed file
# has no other sections. Odoo rewrites this file if the master password is
# changed through the UI; that change is not persisted, and $ODOO_ADMIN_PASSWD
# remains the source of truth on the next boot.
cp /etc/odoo/odoo.conf.base /etc/odoo/odoo.conf
printf 'admin_passwd = %s\n' "$ODOO_ADMIN_PASSWD" >> /etc/odoo/odoo.conf

# --- Tenancy ------------------------------------------------------------------
#
# ONE image, TWO tenants. Print and aluminum serve different markets and never
# interact, so in implementation each gets its own Railway service and its own
# database:
#
#   aluminum   ODOO_ADDONS_PATH=/mnt/extra-addons
#              ODOO_DB_NAME=odoo
#   print      ODOO_ADDONS_PATH=/mnt/extra-addons/addons_print
#              ODOO_DB_NAME=print
#
# Neither variable is set in development, where the committed defaults put both
# trees on one database -- which is the point of defaulting rather than
# requiring them.
#
# These are SUBSTITUTED into the rendered config, not appended: Python's
# configparser rejects a duplicate key in a section, so a second `addons_path =`
# line would abort the boot rather than override.
substitute() {
    key=$1
    value=$2
    # The value is a path list or a database name, so the only character that
    # needs care in a sed replacement is the delimiter; `|` is not legal in
    # either, which is why it is the delimiter.
    sed -i "s|^${key} *=.*|${key} = ${value}|" /etc/odoo/odoo.conf
    # -F, fixed string. dbfilter's value is `^print$`, and the point of
    # this grep is to confirm the line now reads EXACTLY what was asked
    # for. Without -F the value is read as a pattern, and a pattern
    # matches a class of lines rather than the one line intended -- so
    # the verification stops verifying. (It happens to pass today: `$`
    # is literal mid-pattern in a BRE. Working by accident is not the
    # same as working.)
    grep -qF "${key} = ${value}" /etc/odoo/odoo.conf || {
        echo "FATAL: could not set ${key} in the rendered config" >&2
        exit 1
    }
}

if [ -n "${ODOO_ADDONS_PATH:-}" ]; then
    # A path that does not exist is the silent failure to avoid: Odoo starts
    # happily and simply cannot see the modules, so the service comes up with
    # an empty Apps list and nothing explains why.
    echo "$ODOO_ADDONS_PATH" | tr ',' '\n' | while IFS= read -r dir; do
        [ -n "$dir" ] || continue
        if [ ! -d "$dir" ]; then
            echo "FATAL: ODOO_ADDONS_PATH names '$dir', which is not a directory." >&2
            echo "       Odoo would start and find no modules there." >&2
            exit 1
        fi
    done || exit 1
    substitute addons_path "$ODOO_ADDONS_PATH"
    echo "tenancy: addons_path = $ODOO_ADDONS_PATH"
fi

if [ -n "${ODOO_DB_NAME:-}" ]; then
    substitute db_name "$ODOO_DB_NAME"
    # dbfilter has to move with it or the service routes requests to a database
    # it is not configured to create.
    substitute dbfilter "^${ODOO_DB_NAME}\$"
    echo "tenancy: db_name = $ODOO_DB_NAME"
fi

chown -R odoo:odoo /var/lib/odoo /mnt/extra-addons /etc/odoo/odoo.conf
chmod 640 /etc/odoo/odoo.conf

echo "boot: uid=$(id -u) dropping to odoo (uid $(id -u odoo)); config rendered at /etc/odoo/odoo.conf"

# setpriv keeps the current environment, so without this HOME stays /root and
# libpq logs `could not open certificate file "/root/.postgresql/postgresql.crt":
# Permission denied` on every connection attempt. /var/lib/odoo is the odoo
# user's home in the Debian package.
export HOME=/var/lib/odoo

# Hand off to the upstream entrypoint, which waits for PostgreSQL and then
# execs `odoo`. It reads ODOO_RC=/etc/odoo/odoo.conf from the base image.
exec setpriv --reuid=odoo --regid=odoo --init-groups /entrypoint.sh odoo
