#!/usr/bin/env bash
set -euo pipefail

docker compose exec -T fetcher python /app/fetcher/fetch_now.py
docker compose exec -T summarizer python /app/summarizer/run_now.py
