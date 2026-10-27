# Option 1: the browser version, served by nginx.
#
# The server only delivers the app. Statements are opened and analyzed inside each person's
# browser and are never uploaded, so this server holds no case data. The page's security
# policy (also sent as HTTP headers below) lets the browser talk to this server only.
#
#   docker build -f deploy/browser/Dockerfile -t bank-statement-analyzer-browser .
#   docker run -d -p 8080:8080 --read-only --tmpfs /tmp bank-statement-analyzer-browser
#
# Base images are pinned by digest (an exact, unchangeable version).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f
ARG NGINX_IMAGE=nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

FROM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY . .
# Downloads the in-browser Python engine and packages, checking every file's fingerprint. On a
# network that inspects HTTPS, pass your organization's CA certificate (used for the build only):
# docker build --secret id=ca_bundle,src=ca.pem ...
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    python tools/build_offline.py --out /out --cache /src/dist/.download-cache

FROM ${NGINX_IMAGE}
COPY deploy/browser/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /out /usr/share/nginx/html
# nginx runs as an unprivileged user and writes only to /tmp.
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD wget -q -O /dev/null http://127.0.0.1:8080/index.html || exit 1
