# EmailSummaries

A self-hosted AI email pipeline that fetches your Gmail, summarizes each message with a local LLM, and delivers prioritized digests to Telegram — all running on a Raspberry Pi 5. No cloud AI services, no subscriptions, no data leaving your network.

## Highlights

- **100% local AI** — uses [Ollama](https://ollama.com/) to run an LLM entirely on-device; your email content never touches a third-party API
- **Privacy-first** — credentials stay on your hardware, traffic stays on a private Docker network, and the database lives on local storage
- **Runs on a Raspberry Pi 5** — designed for 8 GB RAM and an SSD; lightweight enough for always-on home server use
- **Automated pipeline** — fetches email on a schedule, summarizes immediately, and sends Telegram digests at configurable times
- **VIP & filter rules** — wildcard sender matching, category/label filtering, and priority boosting so you see what matters first

## Tech Stack

| Component | Role |
|-----------|------|
| **Python** | All service code |
| **Docker Compose** | Orchestration (4 containers on a private network) |
| **Ollama** | Local LLM inference (e.g. Gemma 3 1B) |
| **Gmail API** | Read-only OAuth access to your inbox |
| **SQLite (WAL mode)** | Shared queue and state database |
| **Telegram Bot API** | Digest delivery and interactive commands |
| **GitHub Actions** | CI — lint (Ruff) + pytest on every push/PR |

## How It Works

```
Gmail ──▶ Fetcher ──▶ SQLite ──▶ Summarizer ──▶ SQLite ──▶ Telegram Bot ──▶ You
          (filter &      (pending     (local LLM      (processed     (scheduled
           ingest)        queue)       triage)          summaries)     digests)
```

1. **Fetcher** polls Gmail on a schedule, filters out noise (promotions, list-unsubscribe), marks VIPs, and inserts emails as `pending`.
2. **Summarizer** picks up pending emails, builds a prompt with sanitized content, calls Ollama, normalizes priority (1–5), and saves summaries as `processed`.
3. **Telegram Bot** sends prioritized digests on a cron schedule (or on-demand via `/digest`), marking items `delivered`.

## Repository Layout

```text
common/            shared config, SQLite helpers, logging, digest builder
fetcher/           Gmail polling service + one-shot fetch_now.py
summarizer/        Ollama summarization service + one-shot run_now.py
telegram_bot/      Telegram command handler + scheduled digests
config/            config.example.yaml (runtime config template)
scripts/           init_db.py, manual_cycle.sh, generate_gmail_token.py
tests/             pytest suite (20 unit tests)
.github/workflows/ CI pipeline (lint + test)
```

## Getting Started

### 1. Smoke-test Ollama

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull gemma3:1b
docker compose exec ollama ollama list
```

### 2. Configure credentials

```bash
cp config/config.example.yaml config/config.yaml
# Edit config.yaml: add telegram_bot_token, telegram_chat_id, filters, schedules
```

Required host files (bind-mounted at runtime, never baked into images):

- `config/credentials.json` — Google Cloud OAuth client
- `config/config.yaml` — all runtime settings

Generate a Gmail OAuth token:

```bash
python scripts/generate_gmail_token.py
```

### 3. Initialize the database

```bash
python scripts/init_db.py
```

### 4. Build and run

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f fetcher summarizer telegram-bot
```

### 5. Manual trigger

Run one immediate fetch → summarize → digest cycle:

```bash
./scripts/manual_cycle.sh
```

For detailed Raspberry Pi deployment instructions (from OS flashing through verification), see [DEPLOY_PI.md](DEPLOY_PI.md).

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/digest` | Send undelivered summaries now |
| `/status` | Show queue stats and last-run metadata |
| `/search <keyword>` | Search past summaries |

## Testing

Run the test suite (no Docker or external services required):

```bash
pip install -r requirements-test.txt
python -m pytest tests/ -v
```

Lint with [Ruff](https://docs.astral.sh/ruff/):

```bash
ruff check .
```

Both checks run automatically in CI on push and pull requests (see `.github/workflows/tests.yml`).

## License

[MIT](LICENSE)
