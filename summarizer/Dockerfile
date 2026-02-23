FROM python:3.12-slim

# PYTHONPATH allows service modules to import shared code from /app/common.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY summarizer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY summarizer /app/summarizer

# This process schedules triage runs and also supports one-shot run_now.py.
CMD ["python", "/app/summarizer/main.py"]
