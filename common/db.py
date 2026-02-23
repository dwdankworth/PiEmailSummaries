from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def get_database_path(database_path: str | None = None) -> Path:
    return Path(database_path or os.getenv("DATABASE_PATH", "/data/email_summaries.db"))


def connect(database_path: str | None = None) -> sqlite3.Connection:
    path = get_database_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")
    return connection


def init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_id TEXT NOT NULL UNIQUE,
            thread_id TEXT,
            sender TEXT NOT NULL,
            recipients TEXT,
            subject TEXT NOT NULL,
            date TEXT,
            body_text TEXT NOT NULL,
            headers_json TEXT NOT NULL DEFAULT '{}',
            is_vip INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processed','delivered')),
            fetched_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            processed_at TEXT,
            delivered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER NOT NULL UNIQUE,
            summary_text TEXT NOT NULL,
            priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
            categories TEXT NOT NULL DEFAULT '[]',
            priority_reason TEXT NOT NULL,
            processed_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            delivered INTEGER NOT NULL DEFAULT 0,
            delivered_at TEXT,
            model_name TEXT,
            processing_seconds REAL,
            FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS system_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            service TEXT NOT NULL,
            event_type TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_emails_status_vip ON emails(status, is_vip, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_summaries_delivered_priority ON summaries(delivered, priority);
        CREATE INDEX IF NOT EXISTS idx_system_log_service_event ON system_log(service, event_type, timestamp);
        """
    )
    connection.commit()


def initialize_database(database_path: str | None = None) -> None:
    connection = connect(database_path)
    try:
        init_schema(connection)
    finally:
        connection.close()


def record_system_event(
    connection: sqlite3.Connection, service: str, event_type: str, details: dict[str, Any]
) -> None:
    connection.execute(
        """
        INSERT INTO system_log (timestamp, service, event_type, details)
        VALUES (?, ?, ?, ?)
        """,
        (_utcnow(), service, event_type, json.dumps(details, ensure_ascii=True)),
    )
    connection.commit()


def insert_email(
    connection: sqlite3.Connection,
    gmail_id: str,
    thread_id: str | None,
    sender: str,
    recipients: str,
    subject: str,
    date: str,
    body_text: str,
    headers: dict[str, str],
    is_vip: bool,
) -> int | None:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO emails
            (gmail_id, thread_id, sender, recipients, subject, date, body_text, headers_json, is_vip, status, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            gmail_id,
            thread_id,
            sender,
            recipients,
            subject,
            date,
            body_text,
            json.dumps(headers, ensure_ascii=True),
            int(is_vip),
            _utcnow(),
        ),
    )
    connection.commit()
    if cursor.rowcount == 0:
        return None
    return int(cursor.lastrowid)


def fetch_pending_emails(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    cursor = connection.execute(
        """
        SELECT *
        FROM emails
        WHERE status = 'pending'
        ORDER BY is_vip DESC, fetched_at ASC
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def save_summary(
    connection: sqlite3.Connection,
    email_id: int,
    summary_text: str,
    priority: int,
    categories: list[str],
    priority_reason: str,
    model_name: str,
    processing_seconds: float,
) -> None:
    processed_at = _utcnow()
    connection.execute(
        """
        INSERT INTO summaries
            (email_id, summary_text, priority, categories, priority_reason, processed_at, delivered, model_name, processing_seconds)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT(email_id) DO UPDATE SET
            summary_text = excluded.summary_text,
            priority = excluded.priority,
            categories = excluded.categories,
            priority_reason = excluded.priority_reason,
            processed_at = excluded.processed_at,
            delivered = 0,
            delivered_at = NULL,
            model_name = excluded.model_name,
            processing_seconds = excluded.processing_seconds
        """,
        (
            email_id,
            summary_text,
            priority,
            json.dumps(categories, ensure_ascii=True),
            priority_reason,
            processed_at,
            model_name,
            processing_seconds,
        ),
    )
    connection.execute(
        """
        UPDATE emails
        SET status = 'processed', processed_at = ?, delivered_at = NULL
        WHERE id = ?
        """,
        (processed_at, email_id),
    )
    connection.commit()


def fetch_undelivered_processed(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = connection.execute(
        """
        SELECT s.id AS summary_id, s.priority, s.summary_text, s.priority_reason, s.categories,
               s.model_name, s.processing_seconds,
               e.id AS email_id, e.sender, e.subject, e.date, e.is_vip
        FROM summaries s
        JOIN emails e ON e.id = s.email_id
        WHERE s.delivered = 0 AND e.status = 'processed'
        ORDER BY s.priority DESC, e.fetched_at ASC
        """
    )
    return cursor.fetchall()


def mark_delivered(connection: sqlite3.Connection, summary_ids: list[int]) -> None:
    if not summary_ids:
        return
    placeholders = ",".join("?" for _ in summary_ids)
    delivered_at = _utcnow()
    connection.execute(
        f"""
        UPDATE summaries
        SET delivered = 1, delivered_at = ?
        WHERE id IN ({placeholders})
        """,
        (delivered_at, *summary_ids),
    )
    connection.execute(
        f"""
        UPDATE emails
        SET status = 'delivered', delivered_at = ?
        WHERE id IN (
            SELECT email_id FROM summaries WHERE id IN ({placeholders})
        )
        """,
        (delivered_at, *summary_ids),
    )
    connection.commit()


def search_summaries(connection: sqlite3.Connection, keyword: str, limit: int = 20) -> list[sqlite3.Row]:
    like_pattern = f"%{keyword}%"
    cursor = connection.execute(
        """
        SELECT e.sender, e.subject, s.summary_text, s.priority, s.processed_at
        FROM summaries s
        JOIN emails e ON e.id = s.email_id
        WHERE e.subject LIKE ? OR s.summary_text LIKE ? OR s.priority_reason LIKE ?
        ORDER BY s.processed_at DESC
        LIMIT ?
        """,
        (like_pattern, like_pattern, like_pattern, limit),
    )
    return cursor.fetchall()


def status_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    pending_count = connection.execute(
        "SELECT COUNT(*) AS c FROM emails WHERE status = 'pending'"
    ).fetchone()["c"]
    undelivered_count = connection.execute(
        "SELECT COUNT(*) AS c FROM summaries WHERE delivered = 0"
    ).fetchone()["c"]

    def _last_event(service: str, event_type: str) -> str | None:
        row = connection.execute(
            """
            SELECT timestamp
            FROM system_log
            WHERE service = ? AND event_type = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (service, event_type),
        ).fetchone()
        return None if row is None else str(row["timestamp"])

    model_row = connection.execute(
        "SELECT model_name FROM summaries WHERE model_name IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    model_name = None if model_row is None else str(model_row["model_name"])

    return {
        "last_fetch_time": _last_event("fetcher", "fetch_cycle_completed"),
        "pending_queue_size": int(pending_count),
        "undelivered_processed_count": int(undelivered_count),
        "last_summarizer_run": _last_event("summarizer", "summarizer_cycle_completed"),
        "ollama_model_loaded": model_name,
    }
