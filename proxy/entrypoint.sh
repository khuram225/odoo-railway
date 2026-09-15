#!/bin/sh
# Renders nginx.conf for this container, then starts nginx in the foreground.
set -eu

ODOO_HOST="${ODOO_UPSTREAM_HOST:-odoo.railway.internal}"

# nginx needs an explicit `resolver` to do runtime DNS. Read it from the
# container's own resolv.conf so this works in any Railway environment.
RESOLVER="$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf)"
[ -n "$RESOLVER" ] || { echo "FATAL: no nameserver in /etc/resolv.conf" >&2; exit 1; }

# Railway's private resolver is IPv6, and nginx requires IPv6 addresses to be
# bracketed or the config fails to parse.
case "$RESOLVER" in
    *:*) RESOLVER="[$RESOLVER]" ;;
esac

echo "boot: resolver=$RESOLVER upstream=$ODOO_HOST"

sed -e "s|__RESOLVER__|${RESOLVER}|g" \
    -e "s|__ODOO_HOST__|${ODOO_HOST}|g" \
    /etc/nginx/odoo-proxy.conf.in > /etc/nginx/conf.d/default.conf

# Surface a real config error instead of a bare exit code.
nginx -t

exec nginx -g 'daemon off;'
