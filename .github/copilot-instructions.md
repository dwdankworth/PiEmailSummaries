# Copilot Instructions for EmailSummaries

## Build, test, and lint commands

This repository currently has no dedicated lint or unit-test suite checked in (no `pytest`/`ruff` config or test directories). Use the documented runtime validation commands instead:

- Validate compose config:
  - `docker compose config --quiet`
- Build/start full stack:
  - `docker compose up --build -d`
- Start only Ollama for model smoke tests:
  - `docker compose up -d ollama`
  - `docker compose exec ollama ollama pull gemma3:1b`
  - `docker compose exec ollama ollama list`
- Single-cycle functional test (closest equivalent to a single test run):
  - `./scripts/manual_cycle.sh`
  - or:
    - `docker compose exec -T fetcher python /app/fetcher/fetch_now.py`
    - `docker compose exec -T summarizer python /app/summarizer/run_now.py`
- Runtime verification:
  - `docker compose ps`
  - `docker compose logs -f fetcher summarizer`

## High-level architecture

EmailSummaries is a 3-service Docker Compose pipeline around a shared SQLite database:

1. **fetcher** (`fetcher/main.py`, `fetcher/service.py`, `fetcher/gmail_client.py`, `telegram_bot/service.py`, `common/telegram_digest.py`)
   - Combined fetcher + Telegram bot process for lower memory footprint.
   - **Email fetching**: runs on interval schedule (`fetch_interval_minutes`, default 20 min). Pulls Gmail messages, skips noisy categories and list-unsubscribe emails, marks VIP via wildcard sender matching. Inserts unique emails into `emails` table with `status='pending'`.
   - **Telegram bot**: runs `python-telegram-bot` polling. Provides `/digest`, `/status`, `/search` commands (restricted to configured `telegram_chat_id`).
   - **Digest delivery**: schedules digest sends via cron (`digest_schedule`). Also available on-demand via `/digest`. This is the **only** service that sends digests.

2. **summarizer** (`summarizer/main.py`, `summarizer/service.py`)
   - Polls for pending emails on a short interval (`summarizer_interval_minutes`, default 2 min) so emails are summarized promptly after fetching.
   - Builds prompt from configurable template and email metadata, sanitizes untrusted content, truncates body for context limits, calls Ollama with retries.
   - Saves normalized output into `summaries`, updates email status to `processed`. Does **not** trigger digest sends.

3. **ollama** (Compose service)
   - Internal-only LLM endpoint used by summarizer (`ollama_url`). Model is set via `OLLAMA_MODEL` env var in `docker-compose.yml` (currently `gemma3:1b`) and must match `ollama_model` in config.

Shared foundation:
- `common/config.py` defines the full config contract (`AppConfig` frozen dataclass) and defaults.
- `common/db.py` owns schema and all queue/state transitions (`pending -> processed -> delivered`) plus `system_log` events.
- `common/logging_utils.py` standardizes JSON logs for all services.
- `common/telegram_digest.py` builds, chunks, and sends the Telegram digest message; called by the fetcher process.

## Key conventions and repository-specific patterns

- **Config loading contract**: services use `CONFIG_PATH` env var or `/config/config.yaml` (fallback to `config/config.yaml` when running from repo root); keep new settings in both `AppConfig` and `config/config.example.yaml`.
- **Config is a frozen dataclass**: `AppConfig` is `@dataclass(frozen=True)`. New fields need a default value in the dataclass, a loading line in `load_config()`, and validation if the value has constraints.
- **DB path contract**: services default to `DATABASE_PATH=/data/email_summaries.db`; host-side scripts should override to a local writable path when not running in containers.
- **SQLite WAL + retry**: connections use `PRAGMA journal_mode=WAL` for concurrent reads. Write operations that may hit "database is locked" should use `execute_with_retry()` from `common/db.py`.
- **Schema init everywhere**: each service/script opens a DB connection and calls `init_schema()` before work; keep this behavior for new entrypoints.
- **Structured logging pattern**: use `get_logger(service)` and pass contextual data through `extra={"extra_json": {...}}`.
- **Operational telemetry**: significant outcomes are persisted with `record_system_event(...)` and surfaced by `/status`; preserve this when adding flows.
- **Priority normalization**: summarizer boosts model priority for keyword matches and VIP senders, then clamps to 1..5.
- **Prompt injection sanitization**: email subjects and bodies are passed through `_sanitize_for_prompt()` before interpolation into the LLM prompt template. Extend this filter if adding new untrusted content sources.
- **Delivery semantics**: `send_digest_and_mark_delivered` (called only from the fetcher process) is the single place that flips items from processed/undelivered to delivered.
- **Summarizer does not send digests**: the summarizer calls `run_summarizer_cycle(trigger_digest=False)`. Only `run_now.py` uses `trigger_digest=True` for manual one-shot runs.
- **APScheduler misfire grace time**: both fetcher and summarizer set `misfire_grace_time: 900` (15 min) so jobs still fire after device sleep/wake cycles. Preserve this for new scheduled jobs.
- **One-shot entrypoints are first-class**: `fetcher/fetch_now.py` and `summarizer/run_now.py` are used by `scripts/manual_cycle.sh` and should remain compatible with Compose exec flows.
- **Gmail token behavior**: Gmail credentials refresh writes back to `GMAIL_TOKEN_PATH`; ensure writable token path in any new runtime path that may trigger refresh.
- **Container runtime assumptions**: all service images set `PYTHONPATH=/app` and include shared `common/` code; imports and paths should follow that layout.
