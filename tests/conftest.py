from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from common.db import init_schema


@pytest.fixture()
def db_connection():
    """In-memory SQLite database with schema initialised."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def config_file(tmp_path: Path):
    """Write a minimal config YAML and return its path."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent("""\
            vip_senders:
              - "boss@company.com"
              - "*@important.com"
            skip_labels:
              - "CATEGORY_PROMOTIONS"
            priority_keywords:
              - "urgent"
              - "deadline"
            digest_schedule:
              - "0 8 * * *"
            summarizer_interval_minutes: 5
            ollama_model: "test-model"
            telegram_bot_token: "test-token"
            telegram_chat_id: "12345"
            gmail_user_email: "me@gmail.com"
            gmail_max_results: 10
            summarizer_batch_size: 5
            fetch_interval_minutes: 15
            ollama_url: "http://localhost:11434/api/generate"
            ollama_timeout_seconds: 60
            ollama_num_ctx: 4096
            prompt_body_max_chars: 3000
        """),
        encoding="utf-8",
    )
    return str(cfg)
