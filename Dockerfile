# overwatch-db: the database, its pipelines, the inference layer, and the UI
# in one runnable image. See compose.yaml for the intended way to run it.
FROM python:3.12-slim

# Postgres (embedded via pgserver) refuses to run as root, so nothing here
# does. The uid matters for the named volume: docker copies this directory's
# ownership into the volume on first use.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data/raw .cache-blizzard .cache-wiki .cache-counterpick \
    && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    OVERWATCH_DB_UI_HOST=0.0.0.0
EXPOSE 8017

ENTRYPOINT ["./docker-entrypoint.sh"]
