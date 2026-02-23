# EmailSummaries

Local-first email triage for Raspberry Pi 5 using Docker Compose, Ollama, Gmail API, SQLite, and Telegram.

## Services

`docker-compose.yml` defines 4 containers:

1. `ollama` (local LLM API)
2. `fetcher` (Gmail ingest + Tier-1 filtering)
3. `summarizer` (Tier-2 LLM triage + digest trigger)
4. `telegram-bot` (`/digest`, `/status`, `/search`)

Data is stored in SQLite (`email-data` volume), and all services read `config/config.yaml` via read-only bind mount.

## Repository Layout

```text
common/         shared config, SQLite, logging, digest helpers
fetcher/        Gmail polling service + one-shot fetch_now.py
summarizer/     Ollama triage service + one-shot run_now.py
telegram_bot/   Telegram command bot + scheduled digests
config/         config.yaml + config.example.yaml
scripts/        init_db.py + manual_cycle.sh
docker-compose.yml
```

## 1) Docker Fundamentals (Ollama-only smoke test)

Start just Ollama:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull phi3:mini
docker compose exec ollama ollama list
```

Test inference from inside the Docker network:

```bash
docker compose exec ollama sh -lc \
  "curl -s http://localhost:11434/api/generate -d '{\"model\":\"phi3:mini\",\"prompt\":\"Say hi\",\"stream\":false}'"
```

## 2) Configure Gmail + Telegram + runtime config

Copy and edit config:

```bash
cp config/config.example.yaml config/config.yaml
```

Required host files (bind-mounted, never baked into images):

- `config/credentials.json` (Google Cloud OAuth client)
- `config/config.yaml` (`telegram_bot_token`, `telegram_chat_id`, filters, schedules)

Generate Gmail token after adding credentials:

```bash
python scripts/generate_gmail_token.py
```

## 3) Initialize DB schema

```bash
python scripts/init_db.py
```

This creates:

- `emails`
- `summaries`
- `system_log`

SQLite runs in WAL mode via connection pragmas in `common/db.py`.

## 4) Build and run all services

```bash
docker compose up --build -d
```

Check health:

```bash
docker compose ps
docker compose logs -f fetcher summarizer telegram-bot
```

## 5) Manual trigger from SSH

Run one immediate fetch + summarize + digest cycle:

```bash
./scripts/manual_cycle.sh
```

Equivalent commands:

```bash
docker compose exec -T fetcher python /app/fetcher/fetch_now.py
docker compose exec -T summarizer python /app/summarizer/run_now.py
```

## 6) Telegram commands

- `/digest` send undelivered processed summaries now
- `/status` show queue + last run metadata
- `/search <keyword>` search past summaries

## Notes

- Structured JSON logs are emitted by all services for grep-friendly diagnostics.
- Summarizer uses retry logic for Ollama call failures/timeouts.
- Service-to-service traffic stays on a private Docker network (`email-internal`); no host ports are published.
