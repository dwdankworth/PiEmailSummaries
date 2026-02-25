from __future__ import annotations

from fnmatch import fnmatch
from typing import Any

from common.config import AppConfig, load_config
from common.db import connect, init_schema, insert_email, record_system_event
from common.logging_utils import get_logger
from fetcher.gmail_client import build_gmail_service, list_recent_messages

LOGGER = get_logger("fetcher")


def _sender_is_vip(sender_email: str, vip_patterns: list[str]) -> bool:
    normalized_sender = sender_email.strip().lower()
    for pattern in vip_patterns:
        if fnmatch(normalized_sender, pattern.strip().lower()):
            return True
    return False


def _should_skip(message: dict[str, Any], config: AppConfig) -> bool:
    labels = set(message.get("label_ids", []))
    if labels.intersection(set(config.skip_labels)):
        return True
    list_unsubscribe = message.get("headers", {}).get("list-unsubscribe", "")
    return bool(list_unsubscribe.strip())


def run_fetch_cycle(config_path: str | None = None, database_path: str | None = None) -> dict[str, int]:
    config = load_config(config_path)
    service = build_gmail_service()

    connection = connect(database_path)
    init_schema(connection)
    inserted = 0
    duplicates = 0
    skipped = 0
    fetched = 0
    try:
        messages = list_recent_messages(service, config.gmail_max_results)
        fetched = len(messages)
        for message in messages:
            if _should_skip(message, config):
                skipped += 1
                continue

            is_vip = _sender_is_vip(message["sender_email"], config.vip_senders)
            row_id = insert_email(
                connection=connection,
                gmail_id=message["gmail_id"],
                thread_id=message["thread_id"],
                sender=message["sender"],
                recipients=message["recipients"],
                subject=message["subject"],
                date=message["date"],
                body_text=message["body_text"],
                headers=message["headers"],
                is_vip=is_vip,
            )
            if row_id is None:
                duplicates += 1
            else:
                inserted += 1

        stats = {
            "fetched": fetched,
            "inserted": inserted,
            "duplicates": duplicates,
            "skipped": skipped,
        }
        record_system_event(connection, "fetcher", "fetch_cycle_completed", stats)
        LOGGER.info("Fetch cycle completed", extra={"extra_json": stats})
        return stats
    except Exception as exc:
        details = {"error": str(exc)}
        record_system_event(connection, "fetcher", "fetch_cycle_failed", details)
        LOGGER.exception("Fetch cycle failed", extra={"extra_json": details})
        raise
    finally:
        connection.close()
