FROM python:3.12-slim

# Combined fetcher + telegram-bot service for lower memory footprint on Pi.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

COPY fetcher/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY fetcher /app/fetcher
COPY telegram_bot /app/telegram_bot

# Note: bind-mounted files (token.json) must be writable by UID of appuser.
# On host, ensure: chmod 666 config/token.json or match UID.
RUN mkdir -p /data /config /secrets && chown appuser:appuser /data /config /secrets

USER appuser

# Unified entrypoint: runs email fetcher scheduler + Telegram bot in one process.
CMD ["python", "/app/fetcher/main.py"]
