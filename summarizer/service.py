from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from common.config import AppConfig, load_config
from common.db import (
    connect,
    fetch_pending_emails,
    record_system_event,
    save_summary,
)
from common.logging_utils import get_logger
from common.telegram_digest import send_digest_and_mark_delivered

LOGGER = get_logger("summarizer")
_BATCH_OLLAMA_KEEP_ALIVE = "5m"


def validate_ollama_model(config: AppConfig) -> None:
    """Check that the configured model is available in Ollama."""
    try:
        tags_url = config.ollama_url.rsplit("/", 1)[0] + "/tags"
        response = httpx.get(tags_url, timeout=10.0)
        if response.status_code == 200:
            models = [m["name"] for m in response.json().get("models", [])]
            if config.ollama_model not in models:
                LOGGER.warning(
                    "Model %s not found in Ollama. Available: %s",
                    config.ollama_model,
                    models,
                )
    except Exception:
        LOGGER.warning("Could not validate Ollama model availability")


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


_INJECTION_PHRASES = [
    "ignore previous instructions",
    "ignore all previous",
    "ignore above",
    "disregard previous",
    "new instructions",
    "override instructions",
]

_ROLE_LINE_RE = re.compile(r"^(system|assistant|user):", re.IGNORECASE | re.MULTILINE)

_HEADER_LINE_RE = re.compile(r"^###", re.MULTILINE)


def _sanitize_for_prompt(text: str) -> str:
    """Neutralize common prompt injection patterns in untrusted email content.

    This is a lightweight heuristic filter — not a security boundary — that
    strips the most common attempts to hijack the LLM prompt via crafted
    email subjects or bodies before they are interpolated into the template.
    """
    for phrase in _INJECTION_PHRASES:
        # Case-insensitive replacement without regex for simple substrings
        lower = text.lower()
        start = 0
        while True:
            idx = lower.find(phrase, start)
            if idx == -1:
                break
            text = text[:idx] + "[filtered]" + text[idx + len(phrase):]
            lower = text.lower()
            start = idx + len("[filtered]")

    # Remove role markers that could confuse the LLM
    text = _ROLE_LINE_RE.sub("[filtered]", text)

    # Neutralize markdown/formatting injection
    text = text.replace("```", "`")
    text = _HEADER_LINE_RE.sub("# ", text)

    return text


def _build_prompt(config: AppConfig, row: dict[str, Any], matched_keywords: list[str]) -> str:
    headers = json.loads(row["headers_json"])
    body_text = str(row["body_text"])
    if len(body_text) > config.prompt_body_max_chars:
        body_text = (
            body_text[: config.prompt_body_max_chars]
            + "\n\n[...email body truncated for model context window...]"
        )
    body_text = _sanitize_for_prompt(body_text)
    subject = _sanitize_for_prompt(str(row["subject"]))

    # Build user context string for the prompt header
    parts: list[str] = []
    if config.user_name:
        parts.append(f" You are triaging email for {config.user_name}.")
    if config.user_pronouns:
        parts.append(f" Use {config.user_pronouns} pronouns when referring to the recipient.")
    elif parts:
        # Name set but no pronouns — default to neutral language
        parts.append(" Use they/them pronouns or second person (you) when referring to the recipient.")
    user_context = "".join(parts)

    return config.prompt_template.format(
        user_context=user_context,
        is_vip=bool(row["is_vip"]),
        is_direct=_direct_recipient(headers.get("to", ""), config.gmail_user_email),
        thread_depth=_thread_depth(row["subject"]),
        matched_keywords=", ".join(matched_keywords) if matched_keywords else "none",
        sender=row["sender"],
        recipients=headers.get("to", ""),
        subject=subject,
        date=row["date"],
        body_text=body_text,
    )


def _batch_keep_alive(config: AppConfig, batch_size: int, row_index: int) -> str:
    """Keep the model warm across multi-email batches when keep_alive is set to 0.

    Ollama's keep_alive timer applies per request. With a batch of N separate
    requests and keep_alive="0", the model may unload after each email. For
    intermediate emails in a multi-email batch, keep the model warm briefly so
    the next email can reuse the loaded model, then restore the configured
    keep_alive on the final request.
    """
    if batch_size <= 1 or config.ollama_keep_alive != "0":
        return config.ollama_keep_alive
    if row_index == batch_size - 1:
        return config.ollama_keep_alive
    return _BATCH_OLLAMA_KEEP_ALIVE


def _call_ollama(config: AppConfig, prompt: str, keep_alive: str | None = None) -> dict[str, Any]:
    last_error: Exception | None = None
    effective_keep_alive = keep_alive if keep_alive is not None else config.ollama_keep_alive
    for attempt in range(1, 4):
        try:
            response = httpx.post(
                config.ollama_url,
                json={
                    "model": config.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "keep_alive": effective_keep_alive,
                    "options": {"num_ctx": config.ollama_num_ctx},
                },
                timeout=float(config.ollama_timeout_seconds),
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
                "Ollama call attempt %d/%d failed, %s",
                attempt,
                3,
                "retrying" if attempt < 3 else "giving up",
                extra={"extra_json": {"attempt": attempt, "error": str(exc), "model": config.ollama_model}},
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

    started = time.perf_counter()
    processed = 0
    failed = 0
    digest_sent = 0
    try:
        pending_rows = fetch_pending_emails(connection, config.summarizer_batch_size)
        for row_index, row in enumerate(pending_rows):
            row_dict = dict(row)
            cycle_started = time.perf_counter()
            try:
                matched_keywords = _keyword_matches(
                    row_dict["subject"], row_dict["body_text"], config.priority_keywords
                )
                prompt = _build_prompt(config, row_dict, matched_keywords)
                model_output = _call_ollama(
                    config,
                    prompt,
                    keep_alive=_batch_keep_alive(config, len(pending_rows), row_index),
                )
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
