This is an exploration into optimizing team composition strategies. Beginning first with data and an API that is more robust than existing options.

## Run it

**Docker (the whole app, one command):**

```bash
cp .env.example .env      # add your ANTHROPIC_API_KEY
docker compose up
```

First run builds the database (initdb, migrations, every pipeline - it
scrapes the sources once; the mounted caches make later builds cheap), then
serves the UI at http://localhost:8017. Update the data or run anything else
inside the same image:

```bash
docker compose run app python -m orchestrator update
docker compose run app python -m data.proprietary.recommend \
    --map "King's Row" --enemy Zarya --ask "we keep losing the first fight"
docker compose run app pytest -q
```

**Local (no Docker):**

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m orchestrator rebuild
.venv/bin/python ui.py
```

Everything above is free - no key, no account. The one paid feature is
optional: the Recommend button / `recommend.py` calls the Anthropic API
(billed per token at console.anthropic.com; a Claude subscription does not
cover it). Without a key the app says so politely and the evidence preview
does everything except the final model opinion. If you do add a key:
Claude Fable 5.1 at maximum reasoning by default (`OVERWATCH_DB_MODEL` /
`OVERWATCH_DB_EFFORT` in `.env` dial cost down), with server-side refusal
fallbacks, and the stored recommendation records which model answered.
