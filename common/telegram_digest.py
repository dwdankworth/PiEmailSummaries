from __future__ import annotations

import html
from datetime import UTC, datetime

import httpx

from common.config import AppConfig
from common.db import (
    fetch_undelivered_processed,
    mark_delivered,
    record_system_event,
)


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


def send_digest_and_mark_delivered(connection, config: AppConfig, source_service: str) -> int:
    rows = [dict(row) for row in fetch_undelivered_processed(connection)]
    if not rows:
        return 0

    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise ValueError("telegram_bot_token and telegram_chat_id are required to send digests")

    message = _build_digest_text(rows, config.ollama_model)
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
            json={
                "chat_id": config.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30.0,
        )
        response.raise_for_status()
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
