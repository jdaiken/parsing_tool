# Option 2: the server version (the full app, including OCR for scanned statements).
#
# Statements ARE uploaded to this server, so run it only on a server your organization has
# approved for case data, behind its single sign-on, over HTTPS. See docs/UNIVERSITY_DEPLOYMENT.md
# and deploy/server/docker-compose.yml.
#
#   docker build -f deploy/server/Dockerfile -t bank-statement-analyzer-server .
#
# Run it with docker-compose.yml in this folder, which puts it behind your sign-in.
#
# Base image pinned by digest (an exact, unchangeable version).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STATEMENT_PROJECTS_PATH=/data/projects \
    STATEMENT_TEMPLATES_PATH=/data/statement_templates.json \
    HOME=/tmp

WORKDIR /app
COPY requirements-lock.txt .
# Every package is checked against the fingerprint in requirements-lock.txt. On a network that
# inspects HTTPS, pass your organization's CA certificate (used for the build only, never stored
# in the image): docker build --secret id=ca_bundle,src=ca.pem ...
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --require-hashes -r requirements-lock.txt

COPY *.py LICENSE NOTICE ./
COPY assets ./assets
COPY demo ./demo
COPY docs/*.pdf ./docs/
COPY .streamlit ./.streamlit
RUN useradd --system --uid 10001 --home-dir /nonexistent app \
    && mkdir -p /data && chown app /data
USER 10001
VOLUME /data
EXPOSE 8501
# browser.serverAddress is set so Streamlit doesn't look up the server's public IP address online.
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')" || exit 1
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--browser.serverAddress=localhost", \
     "--browser.gatherUsageStats=false", "--server.enableXsrfProtection=true", "--server.enableCORS=true", \
     "--server.fileWatcherType=none", "--server.maxUploadSize=100", "--client.toolbarMode=minimal", \
     "--global.developmentMode=false"]
