# Usage Guide

This guide shows how to configure and run EmailSummaries locally with Docker Compose.

## Prerequisites

- Docker + Docker Compose installed
- Google Cloud Gmail OAuth app configured
- Telegram bot created via BotFather

## 1) Prepare config files

Create your runtime config from the example:

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml` and set at least:

- `gmail_user_email`
- `telegram_bot_token`
- `telegram_chat_id`
- `vip_senders` (optional but recommended)
- `ollama_model` (default `phi3:mini`)
- Optional Ollama tuning if you see slow/timeout summaries:
  - `ollama_timeout_seconds` (default `180`)
  - `ollama_num_ctx` (default `8192`)
  - `prompt_body_max_chars` (default `6000`)

## 2) Add Gmail OAuth files

Place this file in `config/` on the host:

- `config/credentials.json` (OAuth client credentials from Google Cloud Console)

Generate `config/token.json` with:

```bash
python scripts/generate_gmail_token.py
```

This opens a browser for Google consent and writes the authorized token for your account.

These are bind-mounted into the fetcher container and are never baked into images.

## 3) Start Ollama first (quick smoke test)

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull phi3:mini
docker compose exec ollama ollama list
docker compose exec ollama sh -lc \
  "curl -s http://localhost:11434/api/generate -d '{\"model\":\"phi3:mini\",\"prompt\":\"Say hi\",\"stream\":false}'"
```

## 4) Initialize database schema

```bash
python scripts/init_db.py
```

Creates SQLite tables: `emails`, `summaries`, `system_log`.

## 5) Build and start all services

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f fetcher summarizer telegram-bot
```

## 6) Trigger one immediate cycle (SSH/manual)

```bash
./scripts/manual_cycle.sh
```

Equivalent:

```bash
docker compose exec -T fetcher python /app/fetcher/fetch_now.py
docker compose exec -T summarizer python /app/summarizer/run_now.py
```

## 7) Telegram bot commands

- `/digest` send digest now from undelivered processed summaries
- `/status` show fetch/summarizer health and queue counts
- `/search <keyword>` search prior summaries

## Troubleshooting quick checks

- Validate compose file: `docker compose config --quiet`
- See service logs: `docker compose logs -f <service>`
- Verify config values are present (especially Telegram + Gmail fields)
- Ensure `config/token.json` and `config/credentials.json` exist before starting fetcher
