FROM python:3.12-slim

# python-telegram-bot is asyncio-based; we keep the rest of the service sync/simple.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY telegram_bot/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY telegram_bot /app/telegram_bot

CMD ["python", "/app/telegram_bot/main.py"]
