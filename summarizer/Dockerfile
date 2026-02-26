FROM python:3.12-slim

# PYTHONPATH allows service modules to import shared code from /app/common.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -d /app appuser

COPY summarizer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY summarizer /app/summarizer

# Note: bind-mounted files should be owned by UID 1000 on host for least-privilege access.
RUN mkdir -p /data /config && chown appuser:appuser /data /config

USER appuser

# This process schedules triage runs and also supports one-shot run_now.py.
CMD ["python", "/app/summarizer/main.py"]
