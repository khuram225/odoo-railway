# Odoo 19 Community, configured for Railway.
#
# The tag is dated because Odoo rebuilds these images nightly from the 19.0
# stable branch's .deb -- the date IS the version. `latest`, `19`, `19.0` and
# `19.0-20260723` were the same digest when this was pinned.
FROM odoo:19.0-20260723

# The upstream image ends with `USER odoo`. Railway mounts volumes root-owned,
# so the entrypoint needs root to chown the filestore; it drops back to `odoo`
# with setpriv before exec'ing Odoo. Nothing here runs Odoo as root.
USER root

COPY odoo.conf /etc/odoo/odoo.conf.base
COPY entrypoint.sh /usr/local/bin/railway-entrypoint.sh
RUN chmod 0755 /usr/local/bin/railway-entrypoint.sh \
    && chmod 0644 /etc/odoo/odoo.conf.base

# 8069 = HTTP workers, 8072 = gevent worker (websocket bus only).
EXPOSE 8069 8072

ENTRYPOINT ["/usr/local/bin/railway-entrypoint.sh"]
