# overwatch-db: one image for every layer - the data layer's tools and MCP
# server, the inference engine, the board - and the tests. compose.yaml
# runs one container per layer from it (docker-entrypoint.sh picks the role).
FROM python:3.12-slim

# Nothing here runs as root. The uid matters for the bind mounts: files the
# data layer writes (caches, data/raw, transcripts) stay owned by uid 1000.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data/raw .cache-blizzard .cache-wiki .cache-counterpick \
    && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8017 8019 8020

ENTRYPOINT ["./docker-entrypoint.sh"]
