# Odoo 19 Community, configured for Railway.
#
# The tag is dated because Odoo rebuilds these images nightly from the 19.0
# stable branch's .deb -- the date IS the version. `latest`, `19`, `19.0` and
# `19.0-20260723` were the same digest when this was pinned.
FROM odoo:19.0-20260723
COPY ./addons /mnt/extra-addons

# The upstream image ends with `USER odoo`. Railway mounts volumes root-owned,
# so the entrypoint needs root to chown the filestore; it drops back to `odoo`
# with setpriv before exec'ing Odoo. Nothing here runs Odoo as root.
USER root

# LP/MIP solver for the cutting optimiser (spec 8, Phase 6c). Pinned to
# the 2.x line deliberately: pulp 4.x is a rewrite with a different API
# AND no bundled solver, so "pulp" unpinned silently drops the optimiser
# to its greedy fallback -- which on a 9-piece test buys 70 ft where the
# exact method buys 54. 2.9.0 ships CBC in the wheel, so nothing else is
# installed.
#
# --break-system-packages: Debian 12 marks the system Python
# externally-managed (PEP 668). This image has no venv and Odoo runs
# against the system interpreter, so the package has to land there.
RUN pip3 install --no-cache-dir --break-system-packages pulp==2.9.0 \
    && python3 -c "import pulp; assert pulp.listSolvers(onlyAvailable=True), 'no CBC'"

COPY odoo.conf /etc/odoo/odoo.conf.base
COPY entrypoint.sh /usr/local/bin/railway-entrypoint.sh
RUN chmod 0755 /usr/local/bin/railway-entrypoint.sh \
    && chmod 0644 /etc/odoo/odoo.conf.base

# 8069 = HTTP workers, 8072 = gevent worker (websocket bus only).
EXPOSE 8069 8072

ENTRYPOINT ["/usr/local/bin/railway-entrypoint.sh"]
