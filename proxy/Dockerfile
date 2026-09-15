FROM nginx:1.30.4-alpine

# Stock nginx uses `worker_processes auto`, which reads the HOST's core count.
# On Railway that is 48, so it starts ~55 worker processes inside a container
# with a far smaller CPU quota.
RUN sed -i 's/^worker_processes.*/worker_processes 2;/' /etc/nginx/nginx.conf

# Staged outside conf.d, and deliberately not named *.conf, so nginx does not
# load the un-substituted template. Also kept out of /etc/nginx/templates/,
# because the base image runs envsubst over everything in there -- which would
# eat $http_upgrade, $request_uri and every other nginx variable in this file.
COPY nginx.conf /etc/nginx/odoo-proxy.conf.in
COPY entrypoint.sh /usr/local/bin/railway-entrypoint.sh
RUN chmod 0755 /usr/local/bin/railway-entrypoint.sh \
    && chmod 0644 /etc/nginx/odoo-proxy.conf.in \
    && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/railway-entrypoint.sh"]
