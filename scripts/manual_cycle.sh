#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Starting services and waiting for healthy status..."
docker compose up -d --wait --remove-orphans

echo "Running fetch cycle..."
docker compose exec -T fetcher python /app/fetcher/fetch_now.py

echo "Running summarizer cycle (includes digest send)..."
docker compose exec -T summarizer python /app/summarizer/run_now.py

echo "Done."
