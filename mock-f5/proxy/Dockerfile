# syntax=docker/dockerfile:1.7

# Adapter sidecar that gives each multiplexed mock device a dedicated port,
# rewriting /mgmt/... to /<hostname>/mgmt/... before proxying to mock-f5.
# Exists because the F5 Terraform provider has no path-prefix support; see
# README.md in this directory for the source-code references.

FROM nginx:1.27-alpine

RUN apk add --no-cache python3 openssl

COPY render_nginx_conf.py /usr/local/bin/render_nginx_conf.py
RUN chmod +x /usr/local/bin/render_nginx_conf.py

# Self-signed TLS — the F5 Terraform provider hardcodes https://, so even
# the lab adapter must terminate TLS. The cert is bake-time so the image is
# self-contained; provider blocks set `validate_certs = false` to accept it.
RUN openssl req -x509 -nodes -newkey rsa:2048 \
      -keyout /etc/nginx/proxy.key \
      -out /etc/nginx/proxy.crt \
      -days 3650 \
      -subj "/CN=nexusf5-mock-proxy" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
 && chmod 600 /etc/nginx/proxy.key

# Strip default conf so only rendered server blocks listen.
RUN rm -f /etc/nginx/conf.d/default.conf

# Listen ports announced via EXPOSE so docker compose port-publish maps cleanly.
EXPOSE 8101 8102 8103 8104 8105

# Render at container start so the manifest can be edited on the host without
# rebuilding the image.
CMD ["sh", "-c", "python3 /usr/local/bin/render_nginx_conf.py && exec nginx -g 'daemon off;'"]
