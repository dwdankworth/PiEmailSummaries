FROM python:3.12-slim

# PYTHONPATH allows service modules to import shared code from /app/common.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

COPY summarizer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY summarizer /app/summarizer

# Note: bind-mounted files (token.json) must be writable by UID of appuser.
# On host, ensure: chmod 666 config/token.json or match UID.
USER appuser

# This process schedules triage runs and also supports one-shot run_now.py.
CMD ["python", "/app/summarizer/main.py"]
