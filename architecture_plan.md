
# Project Spec: Pi Email Summarizer

You are helping me build a local-first email summarization service that runs on a Raspberry Pi 5 (8GB RAM) using Docker Compose and Ollama. The system fetches emails from Gmail, summarizes and triages them with a local LLM, and delivers digests via a Telegram bot.

I am a data scientist comfortable writing production Python but new to Docker. I want to learn Docker as part of this project, so please explain Docker concepts as they come up and include comments in Dockerfiles and docker-compose.yml. Build the project incrementally — don't dump everything at once. Walk me through it piece by piece so I understand each layer.

## Architecture Overview

The system has **4 Docker containers** orchestrated by **Docker Compose**, plus a SQLite database on a Docker volume and a shared config file via bind mount.

### Containers

1. **Ollama** — Official `ollama/ollama` image. Runs the local LLM. Exposes REST API on port 11434 to the internal Docker network. Start with `phi3:mini` for development, benchmark against `mistral:7b-instruct-q4_K_M` later.

2. **Email Fetcher** — Custom Python container. Polls Gmail API every 15-30 minutes via a scheduler (APScheduler or simple cron loop). Downloads new messages since last check, applies cheap pre-filters (skip Gmail Promotions/Social categories, skip emails with unsubscribe headers), flags VIP senders from the config, and stores raw emails in SQLite with `status='pending'` and `is_vip=true/false`.

3. **Summarizer** — Custom Python container. Runs on a configurable schedule (default: 3x daily at 8am, 1pm, 6pm). Pulls all `status='pending'` emails from SQLite, sends each to Ollama in a single prompt that returns structured JSON with: `summary` (2-3 sentences), `priority` (1-5 integer), `categories` (list of tags), and `priority_reason` (one-line explanation). Processes VIP emails first. Updates SQLite with results and `status='processed'`. After processing, triggers the Telegram bot to send a digest. Must also support manual triggering — expose a simple mechanism so that running a command from SSH (e.g., `docker compose exec summarizer python run_now.py`) immediately processes pending emails and sends a digest.

4. **Telegram Bot** — Custom Python container using `python-telegram-bot` library. Sends scheduled digests and supports on-demand commands:
   - `/digest` — immediately fetch and send a summary of all undelivered processed emails
   - `/status` — report system health: last fetch time, pending queue size, last summarizer run, Ollama model loaded
   - `/search <keyword>` — full-text search across past summaries
   
   The bot does NOT manage VIP lists or config — I'll edit `config.yaml` directly via SSH.

### Storage

- **SQLite** in WAL mode on a named Docker volume (`email-data`). Shared across fetcher, summarizer, and bot containers. Schema should include tables for:
  - `emails` — raw email data, sender, subject, date, gmail_id, body_text, is_vip, status (pending/processed/delivered), fetched_at
  - `summaries` — email_id FK, summary_text, priority, categories (JSON), priority_reason, processed_at, delivered (boolean), delivered_at
  - `system_log` — timestamp, service name, event type, details (for /status command)

- **config.yaml** — Bind-mounted read-only into all containers. Contains:
  - `vip_senders`: list of email addresses and/or domains
  - `skip_labels`: Gmail labels/categories to ignore (default: CATEGORY_PROMOTIONS, CATEGORY_SOCIAL)
  - `priority_keywords`: list of keywords that should boost priority (e.g., "urgent", "deadline", "action required")
  - `digest_schedule`: cron expressions or simple time list for digest runs
  - `ollama_model`: model name string
  - `telegram_bot_token`: bot API token
  - `telegram_chat_id`: your personal chat ID
  - `gmail_max_results`: max emails per fetch cycle
  - `summarizer_batch_size`: max emails per summarizer run (default: 20, to manage Pi thermals)
  - `prompt_template`: the LLM prompt template with placeholders for email content

### Networking & Secrets

- Docker Compose creates a private network. Services reference each other by service name (e.g., summarizer calls `http://ollama:11434/api/generate`).
- Gmail OAuth2 token (`token.json`) and credentials (`credentials.json`) stored on the Pi host and bind-mounted into the fetcher container. Never baked into the Docker image.
- Telegram bot token lives in `config.yaml` (which is also bind-mounted, not in the image).
- No ports need to be published to the host network — everything communicates internally except the fetcher reaching out to Gmail API and the bot reaching out to Telegram API.

## Two-Tier Filtering Strategy

### Tier 1: Pre-filter (in fetcher, no LLM needed)
- Skip emails in Gmail categories: Promotions, Social, Updates (configurable)
- Skip emails with `List-Unsubscribe` header
- Flag VIP senders by matching sender address against `vip_senders` in config (support both full addresses and domain wildcards like `*@company.com`)

### Tier 2: LLM Triage (in summarizer)
- Single Ollama prompt per email returns structured JSON
- Priority scoring considers: VIP status (passed from fetcher), keyword matches, whether the user is directly addressed (To/CC vs BCC/mailing list), thread vs standalone, and the LLM's judgment of urgency/importance
- The prompt should instruct the model to consider these factors explicitly

## LLM Prompt Design

The summarizer should use a single prompt per email. Here's the intent (iterate on exact wording):

```
You are an email triage assistant. Analyze the following email and respond with ONLY valid JSON, no other text.

Context:
- VIP sender: {is_vip}
- Direct recipient (To/CC): {is_direct}
- Thread depth: {thread_depth}
- Priority keywords found: {matched_keywords}

Email:
From: {sender}
To: {recipients}
Subject: {subject}
Date: {date}
Body:
{body_text}

Respond with this exact JSON structure:
{
  "summary": "2-3 sentence summary of the email content and any action items",
  "priority": <integer 1-5, where 5 is most urgent>,
  "categories": ["list", "of", "relevant", "tags"],
  "priority_reason": "One sentence explaining why you assigned this priority"
}
```

## Digest Format (Telegram)

The Telegram digest message should be well-formatted using Telegram's MarkdownV2 or HTML formatting:

- Header with timestamp and count of emails
- High priority section (priority 4-5) listed first, each with: sender, subject, summary, priority indicator
- Medium priority section (priority 2-3)
- Low priority section (priority 1) — just a count and list of subjects, no full summaries
- Footer with stats: total processed, time taken, model used

## Manual Trigger Mechanism

I want to be able to SSH into the Pi and trigger an immediate fetch+summarize+digest cycle. The simplest approach: a shell script on the host that runs:
```bash
#!/bin/bash
docker compose exec fetcher python fetch_now.py
docker compose exec summarizer python run_now.py
```

The Python services should support both scheduled execution (their normal loop) and direct invocation (when called as `python run_now.py` it does one cycle and exits).

## Build Order

Please help me build this incrementally in this order:

1. **Docker fundamentals** — Install Docker and Docker Compose on Pi. Create a minimal docker-compose.yml with just Ollama, verify it works, pull a model, test inference via curl.

2. **Email fetcher** — Set up Gmail API credentials (walk me through Google Cloud Console setup). Build the fetcher container: Dockerfile, requirements, Python code. Test it standalone — verify it fetches and stores emails in SQLite.

3. **Summarizer** — Build the summarizer container. Connect it to Ollama. Iterate on the prompt until the summaries and priority scores are good. Test with real emails.

4. **Telegram bot** — Create a Telegram bot via BotFather. Build the bot container. Test digest formatting.

5. **Integration** — Wire everything together in docker-compose.yml with proper depends_on, healthchecks, volumes, and restart policies. Create the manual trigger script. Test the full pipeline end-to-end.

6. **Hardening** — Add proper logging, error handling, retry logic for Ollama timeouts, and the /status command. Set up the Pi for auto-start on boot.

## Technical Constraints & Preferences

- Python 3.12+
- All custom containers based on `python:3.12-slim`
- Use `httpx` for HTTP calls (to Ollama API), not `requests`
- Use `google-api-python-client` and `google-auth-oauthlib` for Gmail
- Use `python-telegram-bot` library for the bot
- SQLite via Python's built-in `sqlite3` module (no ORM needed, raw SQL is fine)
- APScheduler for scheduling within containers, OR a simple while/sleep loop — your call on which is cleaner
- All config loaded from the bind-mounted config.yaml via PyYAML
- Structured logging (JSON format) so logs are easy to grep
- Type hints throughout
- No ORM, no web framework, no unnecessary dependencies — keep it lean

## What I DON'T Want

- No Redis, no PostgreSQL, no message queue — SQLite is sufficient
- No web dashboard — Telegram is the only UI
- No authentication layer — this runs on my local network
- Don't over-engineer this — it's a personal tool on a Pi, not a production SaaS
- No async Python unless there's a clear benefit — keep it simple with sync code unless you can make a strong case for async in a specific service
