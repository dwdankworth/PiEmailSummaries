# Copilot Instructions for EmailSummaries

## Build, test, and lint commands

This repository currently has no dedicated lint or unit-test suite checked in (no `pytest`/`ruff` config or test directories). Use the documented runtime validation commands instead:

- Validate compose config:
  - `docker compose config --quiet`
- Build/start full stack:
  - `docker compose up --build -d`
- Start only Ollama for model smoke tests:
  - `docker compose up -d ollama`
  - `docker compose exec ollama ollama pull phi3:mini`
  - `docker compose exec ollama ollama list`
- Single-cycle functional test (closest equivalent to a single test run):
  - `./scripts/manual_cycle.sh`
  - or:
    - `docker compose exec -T fetcher python /app/fetcher/fetch_now.py`
    - `docker compose exec -T summarizer python /app/summarizer/run_now.py`
- Runtime verification:
  - `docker compose ps`
  - `docker compose logs -f fetcher summarizer telegram-bot`

## High-level architecture

EmailSummaries is a 4-service Docker Compose pipeline around a shared SQLite database:

1. **fetcher** (`fetcher/main.py`, `fetcher/service.py`, `fetcher/gmail_client.py`)
   - Runs on interval schedule (`fetch_interval_minutes`).
   - Pulls recent Gmail messages, skips noisy categories and list-unsubscribe emails, marks VIP via wildcard sender matching.
   - Inserts unique emails into `emails` table with initial `status='pending'`.

2. **summarizer** (`summarizer/main.py`, `summarizer/service.py`)
   - Runs on cron schedules (`summarizer_schedule`), processes pending emails VIP-first.
   - Builds prompt from configurable template and email metadata, truncates body for context limits, calls Ollama with retries.
   - Saves normalized output into `summaries`, updates email status to `processed`, and may trigger digest send.

3. **telegram-bot** (`telegram_bot/main.py`, `telegram_bot/service.py`, `common/telegram_digest.py`)
   - Provides `/digest`, `/status`, `/search`.
   - Also schedules digest sends via cron (`digest_schedule`).
   - Sends undelivered processed summaries to Telegram, then marks both summary/email as delivered.

4. **ollama** (Compose service)
   - Internal-only LLM endpoint used by summarizer (`ollama_url`).

Shared foundation:
- `common/config.py` defines the full config contract and defaults.
- `common/db.py` owns schema and all queue/state transitions (`pending -> processed -> delivered`) plus `system_log` events.
- `common/logging_utils.py` standardizes JSON logs for all services.

## Key conventions and repository-specific patterns

- **Config loading contract**: services use `CONFIG_PATH` env var or `/config/config.yaml` (fallback to `config/config.yaml` when running from repo root); keep new settings in both `AppConfig` and `config/config.example.yaml`.
- **DB path contract**: services default to `DATABASE_PATH=/data/email_summaries.db`; host-side scripts should override to a local writable path when not running in containers.
- **Schema init everywhere**: each service/script opens a DB connection and calls `init_schema()` before work; keep this behavior for new entrypoints.
- **Structured logging pattern**: use `get_logger(service)` and pass contextual data through `extra={"extra_json": {...}}`.
- **Operational telemetry**: significant outcomes are persisted with `record_system_event(...)` and surfaced by `/status`; preserve this when adding flows.
- **Priority normalization**: summarizer boosts model priority for keyword matches and VIP senders, then clamps to 1..5.
- **Delivery semantics**: digest sender (`send_digest_and_mark_delivered`) is the only place that flips items from processed/undelivered to delivered.
- **One-shot entrypoints are first-class**: `fetcher/fetch_now.py` and `summarizer/run_now.py` are used by `scripts/manual_cycle.sh` and should remain compatible with Compose exec flows.
- **Gmail token behavior**: Gmail credentials refresh writes back to `GMAIL_TOKEN_PATH`; ensure writable token path in any new runtime path that may trigger refresh.
- **Container runtime assumptions**: all service images set `PYTHONPATH=/app` and include shared `common/` code; imports and paths should follow that layout.
