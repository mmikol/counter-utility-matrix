# counter-utility-matrix: one image for every layer - the data layer's tools and
# MCP server, the inference engine, the board - and the tests. compose.yaml runs
# one container per layer from it; docker-entrypoint.sh picks the role.
FROM python:3.12-slim

# Nothing here runs as root. Files the data layer writes (caches, db/raw, the
# playbook) stay owned by the bind mounts' owner: uid 1000 by default,
# COUNTER_MATRIX_UID/GID on a Linux host whose checkout belongs to someone else
# (compose.yaml).
RUN useradd --create-home --uid 1000 app
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p db/raw .cache-blizzard .cache-wiki \
    && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8017 8019 8020

ENTRYPOINT ["./docker-entrypoint.sh"]
