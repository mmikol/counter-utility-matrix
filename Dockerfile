# countrix: one image for every role - the door (the MCP server and its tools),
# the inference service, the board, the refresher, the sentry - and the tests.
# compose.yaml runs one container per role from it; docker-entrypoint.sh picks
# the role.
FROM python:3.12-slim

# Nothing here runs as root. Files the containers write (caches, db/raw, the
# playbook) stay owned by the bind mounts' owner: uid 1000 by default,
# COUNTRIX_UID/GID on a Linux host whose checkout belongs to someone else
# (compose.yaml).
RUN useradd --create-home --uid 1000 app
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
# without pgserver: the embedded cluster is a host build target, and inside the
# image every layer reaches a real postgres service over DATABASE_URL
RUN grep -v '^pgserver' requirements.txt | pip install --no-cache-dir -r /dev/stdin

COPY . .
RUN mkdir -p db/raw .cache-blizzard .cache-wiki \
    && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8017 8019 8020

ENTRYPOINT ["./docker-entrypoint.sh"]
