from __future__ import annotations

import html
import time
from datetime import UTC, datetime

import httpx

from common.config import AppConfig
from common.db import (
    fetch_undelivered_processed,
    mark_delivered,
    record_system_event,
)
from common.logging_utils import get_logger

LOGGER = get_logger("telegram")
_TELEGRAM_MAX_RETRIES = 3


def _send_telegram_with_retry(url: str, json_payload: dict, max_retries: int = _TELEGRAM_MAX_RETRIES) -> httpx.Response:
    """Send a Telegram API request with retry logic for transient errors."""
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = httpx.post(url, json=json_payload, timeout=30.0)
            response.raise_for_status()
            return response
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_error = exc
            LOGGER.warning(
                "Telegram request failed, retrying",
                extra={"extra_json": {"attempt": attempt + 1, "error": str(exc)}},
            )
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code < 500:
                raise  # Don't retry client errors
            LOGGER.warning(
                "Telegram server error %s, retrying",
                exc.response.status_code,
                extra={"extra_json": {"attempt": attempt + 1, "error": str(exc)}},
            )
        if attempt < max_retries - 1:
            time.sleep(1.0 * (2 ** attempt))
    raise last_error  # type: ignore[misc]


_MAX_MESSAGE_LENGTH = 4000  # safe margin below Telegram's 4096 limit


def _build_digest_text(rows: list[dict], fallback_model: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    high = [row for row in rows if int(row["priority"]) >= 4]
    medium = [row for row in rows if 2 <= int(row["priority"]) <= 3]
    low = [row for row in rows if int(row["priority"]) <= 1]

    lines: list[str] = [f"<b>Email Digest</b> ({timestamp})", f"Total emails: {len(rows)}", ""]
    if high:
        lines.append("<b>High priority (4-5)</b>")
        for row in high:
            lines.append(
                f"• <b>[P{row['priority']}]</b> {html.escape(row['subject'])}\n"
                f"  From: {html.escape(row['sender'])}\n"
                f"  {html.escape(row['summary_text'])}"
            )
        lines.append("")
    if medium:
        lines.append("<b>Medium priority (2-3)</b>")
        for row in medium:
            lines.append(
                f"• <b>[P{row['priority']}]</b> {html.escape(row['subject'])}\n"
                f"  From: {html.escape(row['sender'])}\n"
                f"  {html.escape(row['summary_text'])}"
            )
        lines.append("")
    if low:
        lines.append(f"<b>Low priority (1)</b> — {len(low)} email(s)")
        for row in low:
            lines.append(f"• {html.escape(row['subject'])}")
        lines.append("")

    total_seconds = sum(float(row["processing_seconds"] or 0.0) for row in rows)
    model_name = next((str(row["model_name"]) for row in rows if row["model_name"]), fallback_model)
    lines.append(
        f"<i>Stats: total processed {len(rows)}, time taken {total_seconds:.1f}s, model {html.escape(model_name)}</i>"
    )
    return "\n".join(lines)


def _split_digest_text(full_text: str) -> list[str]:
    """Split a digest message into chunks that fit within Telegram's limit.

    Splits at bullet-point (``•``) entry boundaries so no single email
    entry is broken across messages.  Returns a one-element list when the
    text already fits.
    """
    if len(full_text) <= _MAX_MESSAGE_LENGTH:
        return [full_text]

    # Separate the text into individual lines, preserving section headers
    # and bullet entries as atomic units.  Bullet entries may span multiple
    # lines (they start with "•" and subsequent indented lines belong to the
    # same entry).
    raw_lines = full_text.split("\n")
    entries: list[str] = []
    current: list[str] = []
    for line in raw_lines:
        if line.startswith("•") and current:
            entries.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        entries.append("\n".join(current))

    # Build chunks that stay under the limit.
    chunks: list[str] = []
    chunk_entries: list[str] = []
    chunk_len = 0

    for entry in entries:
        # +1 for the newline joining entries
        added = len(entry) + (1 if chunk_entries else 0)
        if chunk_entries and chunk_len + added > _MAX_MESSAGE_LENGTH:
            chunks.append("\n".join(chunk_entries))
            chunk_entries = [entry]
            chunk_len = len(entry)
        else:
            chunk_entries.append(entry)
            chunk_len += added
    if chunk_entries:
        chunks.append("\n".join(chunk_entries))

    if len(chunks) <= 1:
        return chunks

    # Re-label chunks with part numbers.  The first chunk keeps its original
    # header; subsequent chunks get a continuation header.
    total = len(chunks)
    labelled: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        if idx == 1:
            # Inject part indicator into the existing header line
            chunk = chunk.replace(
                "<b>Email Digest</b>",
                f"<b>Email Digest</b> (part {idx} of {total})",
                1,
            )
        else:
            chunk = f"<b>Email Digest</b> (part {idx} of {total})\n\n{chunk}"
        labelled.append(chunk)

    return labelled


def send_digest_and_mark_delivered(connection, config: AppConfig, source_service: str) -> int:
    rows = [dict(row) for row in fetch_undelivered_processed(connection)]
    if not rows:
        return 0

    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise ValueError("telegram_bot_token and telegram_chat_id are required to send digests")

    full_text = _build_digest_text(rows, config.ollama_model)
    chunks = _split_digest_text(full_text)
    try:
        url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
        for chunk in chunks:
            json_payload = {
                "chat_id": config.telegram_chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            response = _send_telegram_with_retry(url, json_payload)
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError(f"Telegram API returned failure: {payload}")
    except Exception as exc:
        record_system_event(
            connection,
            source_service,
            "digest_failed",
            {"error": str(exc), "count": len(rows)},
        )
        raise

    summary_ids = [int(row["summary_id"]) for row in rows]
    mark_delivered(connection, summary_ids)
    record_system_event(
        connection,
        source_service,
        "digest_sent",
        {"count": len(summary_ids), "chat_id": config.telegram_chat_id},
    )
    return len(summary_ids)
