from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from common.config import AppConfig
from common.db import connect, init_schema, record_system_event, search_summaries, status_snapshot
from common.telegram_digest import send_digest_and_mark_delivered


def run_digest(config: AppConfig, database_path: str | None = None) -> int:
    connection = connect(database_path)
    try:
        init_schema(connection)
        sent = send_digest_and_mark_delivered(connection, config, "telegram-bot")
        return sent
    finally:
        connection.close()


def get_status(config: AppConfig, database_path: str | None = None) -> dict[str, str | int | None]:
    connection = connect(database_path)
    try:
        init_schema(connection)
        result = status_snapshot(connection)
        return result
    finally:
        connection.close()


def search_digest_items(keyword: str, database_path: str | None = None) -> list[str]:
    connection = connect(database_path)
    try:
        init_schema(connection)
        rows = search_summaries(connection, keyword=keyword, limit=10)
        return [
            f"[P{row['priority']}] {row['subject']} — {row['summary_text']}"
            for row in rows
        ]
    finally:
        connection.close()


def record_bot_event(event_type: str, details: dict[str, str | int], database_path: str | None = None) -> None:
    connection = connect(database_path)
    try:
        init_schema(connection)
        record_system_event(connection, "telegram-bot", event_type, details)
    finally:
        connection.close()
