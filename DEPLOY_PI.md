# Deploying EmailSummaries on a Raspberry Pi 5

## 1. What This Does

EmailSummaries automatically fetches your Gmail, summarizes each email using a
local AI model running entirely on your Pi, and sends you prioritized digests
via Telegram. No cloud AI services, no subscriptions — everything runs at home.

## 2. What You Need

| Item | Notes |
|------|-------|
| Raspberry Pi 5 (8 GB RAM) | The 4 GB model won't have enough memory for the AI model |
| MicroSD card (32 GB+) or USB SSD | SSD strongly recommended — better reliability and speed |
| Power supply (USB-C, 5V/5A) | Use the official Pi 5 power supply |
| Ethernet or WiFi | Ethernet is more reliable for a headless server |
| Gmail account | You'll create API credentials for read-only access |
| Telegram account | You'll create a bot that sends you digests |
| Another computer | For initial setup (flashing the SD card, generating Gmail token) |

## 3. Flash Raspberry Pi OS

1. Download and install [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
   on your computer.

2. Insert your microSD card (or USB SSD via adapter).

3. In Imager:
   - **Device:** Raspberry Pi 5
   - **Operating System:** Raspberry Pi OS Lite (64-bit)
     — this is a headless (no desktop) version, which is all you need for a server
   - **Storage:** Select your card/SSD

4. Click the **gear icon** (or "Edit Settings") before writing:
   - **Set hostname:** e.g. `emailpi`
   - **Enable SSH:** Use password authentication (or add your SSH key)
   - **Set username and password:** Pick something you'll remember
   - **Configure WiFi** (if not using Ethernet): Enter your network name and password

5. Click **Write** and wait for it to finish.

6. Insert the card into your Pi, plug in power, and wait about a minute for it
   to boot.

7. SSH in from your computer:
   ```bash
   ssh your-username@emailpi.local
   ```
   If `emailpi.local` doesn't resolve, find the Pi's IP address from your router
   admin page and use `ssh your-username@192.168.x.x` instead.

## 4. Install Docker

Docker is a tool that packages applications and their dependencies into
containers. It means you don't have to install Python, libraries, or the AI
runtime manually — everything is bundled and ready to go.

Run these commands on your Pi:

```bash
# Download and run the official Docker installer
curl -fsSL https://get.docker.com | sh

# Let your user run Docker without typing "sudo" every time
sudo usermod -aG docker $USER
```

**Log out and log back in** for the group change to take effect:

```bash
exit
# Then SSH back in
ssh your-username@emailpi.local
```

Verify Docker is working:

```bash
docker --version
# Should print something like: Docker version 28.x.x
```

## 5. Clone This Repository

```bash
git clone https://github.com/dwdankworth/EmailSummaries.git ~/EmailSummaries
cd ~/EmailSummaries
```

This creates an `EmailSummaries` folder in your home directory with all the
code and configuration templates.

## 6. Set Up Gmail API Credentials

This step gives the application read-only access to your Gmail. It cannot send
emails, delete anything, or modify your account.

### Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and sign in
   with the Gmail account you want to monitor.

2. Click the project dropdown at the top of the page → **New Project**.
   - Name it something like `EmailSummaries`
   - Click **Create**

3. Make sure your new project is selected in the dropdown.

### Enable the Gmail API

1. Go to **APIs & Services → Library** (or search "Gmail API" in the top bar).
2. Click **Gmail API** → **Enable**.

### Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** → **Create**.
3. Fill in:
   - **App name:** `EmailSummaries`
   - **User support email:** your email
   - **Developer contact email:** your email
4. Click **Save and Continue** through the remaining steps.
5. Under **Test users**, add your Gmail address.
6. Click **Save and Continue** → **Back to Dashboard**.

### Create OAuth Credentials

1. Go to **APIs & Services → Credentials**.
2. Click **+ Create Credentials → OAuth client ID**.
3. **Application type:** Desktop app
4. **Name:** `EmailSummaries` (or anything you like)
5. Click **Create**.
6. Click **Download JSON** — this downloads a file like `client_secret_...json`.

### Copy Credentials to the Pi

From your computer, copy the downloaded file to the Pi:

```bash
scp ~/Downloads/client_secret_*.json your-username@emailpi.local:~/EmailSummaries/config/credentials.json
```

### Generate the Gmail Token

This step opens a browser window for you to authorize access. You need to run
it on a computer with a browser — either your desktop, or on the Pi if you have
a way to forward the browser (the tool supports a local redirect).

**Option A — Run on your computer (recommended):**

On your computer, install the dependency and run the script:

```bash
pip install google-auth-oauthlib
cd ~/EmailSummaries   # or wherever you cloned the repo locally
python scripts/generate_gmail_token.py
```

A browser window opens. Sign in with your Gmail account and grant read-only
access. The script creates `config/token.json`. Copy it to the Pi:

```bash
scp config/token.json your-username@emailpi.local:~/EmailSummaries/config/token.json
```

**Option B — Run on the Pi with SSH port forwarding:**

```bash
# From your computer, SSH with port forwarding:
ssh -L 8080:localhost:8080 your-username@emailpi.local

# On the Pi:
cd ~/EmailSummaries
pip install google-auth-oauthlib
python scripts/generate_gmail_token.py --port 8080
```

Open the URL that the script prints in a browser on your computer.

### Verify you have both files

```bash
ls -la ~/EmailSummaries/config/credentials.json ~/EmailSummaries/config/token.json
```

Both files should exist. If either is missing, revisit the steps above.

## 7. Set Up Telegram Bot

### Create the Bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`.
3. Choose a name (e.g. `My Email Digest`) and a username (e.g.
   `myemail_digest_bot` — must end in `bot`).
4. BotFather replies with a **token** like `123456789:ABCdefGHI...`. Copy this —
   you'll need it in the next step.

### Get Your Chat ID

The bot needs to know who to send messages to — that's your chat ID.

1. **Send any message** to your new bot in Telegram (e.g. "hello").
2. Open this URL in your browser (replace `YOUR_TOKEN` with your bot token):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Look for `"chat":{"id":123456789` in the response. That number is your chat
   ID. It's usually a positive number for personal chats.

**Alternative:** Message **@userinfobot** on Telegram — it replies with your
user ID, which is the same as your chat ID for direct messages.

## 8. Configure the Application

Copy the example configuration and edit it:

```bash
cd ~/EmailSummaries
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

Here's what to change — the three **required** settings:

| Setting | What to enter |
|---------|---------------|
| `telegram_bot_token` | The token from BotFather (step 7) |
| `telegram_chat_id` | Your chat ID (step 7) |
| `gmail_user_email` | Your Gmail address, e.g. `you@gmail.com` |

Optional settings you might want to adjust:

| Setting | Default | What it does |
|---------|---------|-------------|
| `fetch_interval_minutes` | `20` | How often to check Gmail (in minutes) |
| `ollama_model` | `gemma3:1b` | AI model to use — `gemma3:1b` is a good fit for the Pi |
| `vip_senders` | `[]` | Email addresses that always get high priority. Supports wildcards like `*@company.com` |
| `priority_keywords` | `["urgent", "deadline", "action required"]` | Words in emails that boost priority |
| `digest_schedule` | 8am, 1pm, 6pm | Cron expressions for when digests are sent |
| `skip_labels` | Promotions, Social, Updates | Gmail categories to ignore |
| `ollama_keep_alive` | `"0"` | How long to keep the AI model in memory after a request. `"0"` frees RAM immediately (best for Pi) |

Save and exit nano: press `Ctrl+X`, then `Y`, then `Enter`.

### Lock Down Permissions

Your config and token files contain secrets. Restrict access:

```bash
chmod 600 config/config.yaml config/token.json
```

## 9. Start Everything

```bash
cd ~/EmailSummaries
docker compose up -d
```

**What happens on first run:**

1. Docker downloads the base images (Python, Ollama) — this takes a few minutes
   depending on your internet speed.
2. Docker builds the fetcher and summarizer containers.
3. Ollama downloads the AI model (`gemma3:1b` is about 1 GB).
4. Once the model is ready, the fetcher and summarizer start.

The entire first startup can take **5-10 minutes**. Subsequent starts are much
faster since everything is cached.

Check that all services are running:

```bash
docker compose ps
```

You should see three services (`ollama`, `fetcher`, `summarizer`) with status
`Up` or `healthy`.

Watch the logs to see activity in real time:

```bash
docker compose logs -f
```

Press `Ctrl+C` to stop watching logs (the services keep running).

## 10. Verify It Works

1. **Send yourself a test email** from another account (or to yourself).

2. **Wait for the fetch interval** (20 minutes by default), or trigger
   everything manually:

   ```bash
   # Fetch new emails now
   docker compose exec -T fetcher python /app/fetcher/fetch_now.py

   # Summarize them now
   docker compose exec -T summarizer python /app/summarizer/run_now.py
   ```

3. **Check Telegram.** If a digest schedule has passed, you'll get a message
   automatically. Otherwise, open your bot and send `/digest` to request one
   immediately.

✅ If you see a summarized email in Telegram, everything is working.

### Telegram Bot Commands

| Command | What it does |
|---------|-------------|
| `/digest` | Send all undelivered summaries right now |
| `/status` | Show system status — queue size, last run times |
| `/search keyword` | Search past email summaries |

## 11. Monitoring & Maintenance

### View Logs

```bash
# All services, follow mode
docker compose logs -f

# Just one service
docker compose logs -f fetcher
docker compose logs -f summarizer
docker compose logs -f ollama
```

### Restart Services

```bash
# Restart everything
docker compose restart

# Restart just one service
docker compose restart fetcher
```

### Update to Latest Version

```bash
cd ~/EmailSummaries
git pull
docker compose up --build -d
```

This pulls the latest code and rebuilds the containers. Your configuration,
database, and AI model are preserved — they live on Docker volumes and in
your `config/` folder.

### Check Disk Space

```bash
df -h
```

The database and Docker images live on your SD card / SSD. If space gets low:

```bash
# Remove unused Docker data (old images, stopped containers)
docker system prune -f
```

### Back Up the Database

The email database is stored in a Docker volume. To copy it out:

```bash
docker compose exec -T fetcher cat /data/email_summaries.db > ~/email_summaries_backup.db
```

To restore from a backup:

```bash
docker compose down
docker compose run --rm -v ~/email_summaries_backup.db:/backup.db fetcher \
  cp /backup.db /data/email_summaries.db
docker compose up -d
```

### Auto-Start on Boot

Docker is configured to start on boot by default. Because the services use
`restart: unless-stopped`, they will come back automatically after a reboot or
power outage. No extra setup needed.

## 12. Troubleshooting

### "Out of memory" or services getting killed

The AI model needs significant RAM. Check current memory usage:

```bash
docker stats --no-stream
```

If Ollama is using too much memory:
- Make sure `ollama_keep_alive` is `"0"` in your config (frees memory between
  requests).
- The `gemma3:1b` model is recommended for Pi. Larger models like `mistral:7b`
  need more RAM and may cause instability.

### "Database is locked"

SQLite occasionally locks when multiple services access it simultaneously. This
usually resolves within seconds. If it persists:

```bash
docker compose restart
```

### Gmail token expired

Google OAuth tokens expire periodically. If the fetcher logs show
authentication errors:

```bash
# Re-run on your computer
python scripts/generate_gmail_token.py

# Copy the new token to the Pi
scp config/token.json your-username@emailpi.local:~/EmailSummaries/config/token.json

# Restart the fetcher
docker compose restart fetcher
```

### Telegram bot not responding

```bash
# Check if the bot service is running
docker compose ps

# Check for errors
docker compose logs --tail 50 fetcher
```

Common causes:
- Wrong `telegram_bot_token` or `telegram_chat_id` in config
- You haven't sent a message to the bot yet (it can't initiate contact)

### Services keep restarting

```bash
docker compose logs --tail 100
```

Look for error messages near the end. Common causes:
- Missing or malformed `config/config.yaml`
- Missing `config/credentials.json` or `config/token.json`
- Wrong permissions on config files

### Ollama model failed to download

```bash
docker compose logs ollama
```

If the model download was interrupted, restart Ollama to retry:

```bash
docker compose restart ollama
```

### Everything seems stuck

Nuclear option — rebuild from scratch (your config and database are preserved):

```bash
docker compose down
docker compose up --build -d
```

## 13. Resource Usage

Expected resource usage on a Raspberry Pi 5 (8 GB):

| State | RAM | CPU | Notes |
|-------|-----|-----|-------|
| Idle (between fetches) | ~2-3 GB | Minimal | Ollama unloads the model when `keep_alive` is `"0"` |
| Fetching email | ~2-3 GB | Low | Network I/O, minimal processing |
| Summarizing | ~4-5 GB | High (briefly) | AI model loaded, runs for a few seconds per email |

**Disk usage:**
- Docker images: ~2 GB
- AI model (`gemma3:1b`): ~1 GB
- Database: starts small, grows slowly (a few MB per thousand emails)
- Total initial footprint: ~3 GB

**Network:**
- Gmail API calls every 20 minutes (a few KB each)
- Telegram API calls for digests (a few KB each)
- AI runs entirely locally — no data sent to external AI services

**Temperature:** The Pi will warm up during summarization. A heatsink or case
with passive cooling is recommended. The workload is bursty (a few seconds of
processing, then idle), so thermal throttling is unlikely under normal use.
