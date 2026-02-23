FROM python:3.12-slim

# Keep dependencies minimal and deterministic for Raspberry Pi friendly builds.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY fetcher/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY fetcher /app/fetcher

# The scheduler runs continuously in this container.
CMD ["python", "/app/fetcher/main.py"]
