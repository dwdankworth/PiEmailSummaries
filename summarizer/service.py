from __future__ import annotations

import json
import time
from pathlib import Path
import sys
from typing import Any

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1]))

from common.config import AppConfig, load_config
from common.db import (
    connect,
    fetch_pending_emails,
    init_schema,
    record_system_event,
    save_summary,
)
from common.logging_utils import get_logger
from common.telegram_digest import send_digest_and_mark_delivered

LOGGER = get_logger("summarizer")


def _direct_recipient(recipients: str, user_email: str) -> bool:
    if not recipients.strip() or not user_email.strip():
        return False
    return user_email.lower() in recipients.lower()


def _thread_depth(subject: str) -> int:
    lowered = subject.lower()
    return max(1, lowered.count("re:") + 1)


def _keyword_matches(subject: str, body: str, priority_keywords: list[str]) -> list[str]:
    text = f"{subject}\n{body}".lower()
    return [keyword for keyword in priority_keywords if keyword.lower() in text]


def _build_prompt(config: AppConfig, row: dict[str, Any], matched_keywords: list[str]) -> str:
    headers = json.loads(row["headers_json"])
    return config.prompt_template.format(
        is_vip=bool(row["is_vip"]),
        is_direct=_direct_recipient(headers.get("to", ""), config.gmail_user_email),
        thread_depth=_thread_depth(row["subject"]),
        matched_keywords=", ".join(matched_keywords) if matched_keywords else "none",
        sender=row["sender"],
        recipients=headers.get("to", ""),
        subject=row["subject"],
        date=row["date"],
        body_text=row["body_text"],
    )


def _call_ollama(config: AppConfig, prompt: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = httpx.post(
                config.ollama_url,
                json={
                    "model": config.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=90.0,
            )
            response.raise_for_status()
            payload = response.json()
            raw_response = payload.get("response", "{}")
            parsed = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
            if not isinstance(parsed, dict):
                raise ValueError(f"Unexpected Ollama payload type: {type(parsed)!r}")
            if "summary" not in parsed or "priority" not in parsed:
                raise ValueError(f"Missing required fields in model output: {parsed}")
            return parsed
        except Exception as exc:  # retry and surface if all retries fail
            last_error = exc
            LOGGER.warning(
                "Ollama call failed, retrying",
                extra={"extra_json": {"attempt": attempt, "error": str(exc)}},
            )
            time.sleep(attempt * 2)
    if last_error is None:
        raise RuntimeError("Ollama call failed with unknown error")
    raise last_error


def _normalize_summary(model_output: dict[str, Any], matched_keywords: list[str], is_vip: bool) -> dict[str, Any]:
    priority = int(model_output.get("priority", 1))
    if matched_keywords:
        priority += 1
    if is_vip:
        priority += 1
    priority = max(1, min(5, priority))

    categories_raw = model_output.get("categories", [])
    if isinstance(categories_raw, list):
        categories = [str(item) for item in categories_raw]
    else:
        categories = [str(categories_raw)]

    return {
        "summary": str(model_output.get("summary", "")).strip(),
        "priority": priority,
        "categories": categories,
        "priority_reason": str(model_output.get("priority_reason", "No reason provided")).strip(),
    }


def run_summarizer_cycle(
    trigger_digest: bool = True,
    config_path: str | None = None,
    database_path: str | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    connection = connect(database_path)
    init_schema(connection)

    started = time.perf_counter()
    processed = 0
    failed = 0
    digest_sent = 0
    try:
        pending_rows = fetch_pending_emails(connection, config.summarizer_batch_size)
        for row in pending_rows:
            row_dict = dict(row)
            cycle_started = time.perf_counter()
            try:
                matched_keywords = _keyword_matches(
                    row_dict["subject"], row_dict["body_text"], config.priority_keywords
                )
                prompt = _build_prompt(config, row_dict, matched_keywords)
                model_output = _call_ollama(config, prompt)
                normalized = _normalize_summary(
                    model_output, matched_keywords, bool(row_dict["is_vip"])
                )
                processing_seconds = time.perf_counter() - cycle_started
                save_summary(
                    connection=connection,
                    email_id=int(row_dict["id"]),
                    summary_text=normalized["summary"],
                    priority=int(normalized["priority"]),
                    categories=normalized["categories"],
                    priority_reason=normalized["priority_reason"],
                    model_name=config.ollama_model,
                    processing_seconds=processing_seconds,
                )
                processed += 1
            except Exception as exc:
                failed += 1
                record_system_event(
                    connection,
                    "summarizer",
                    "summarizer_email_failed",
                    {"email_id": int(row_dict["id"]), "error": str(exc)},
                )
                LOGGER.exception(
                    "Failed to summarize one email",
                    extra={"extra_json": {"email_id": int(row_dict["id"]), "error": str(exc)}},
                )

        if trigger_digest:
            digest_sent = send_digest_and_mark_delivered(connection, config, "summarizer")

        total_duration = time.perf_counter() - started
        result = {
            "processed": processed,
            "failed": failed,
            "digest_sent_count": digest_sent,
            "duration_seconds": round(total_duration, 3),
            "model": config.ollama_model,
        }
        record_system_event(connection, "summarizer", "summarizer_cycle_completed", result)
        LOGGER.info("Summarizer cycle completed", extra={"extra_json": result})
        return result
    except Exception as exc:
        details = {"error": str(exc)}
        record_system_event(connection, "summarizer", "summarizer_cycle_failed", details)
        LOGGER.exception("Summarizer cycle failed", extra={"extra_json": details})
        raise
    finally:
        connection.close()
