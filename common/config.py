from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROMPT_TEMPLATE = """You are an email triage assistant. Analyze the following email and respond with ONLY valid JSON, no other text.

Context:
- VIP sender: {is_vip}
- Direct recipient (To/CC): {is_direct}
- Thread depth: {thread_depth}
- Priority keywords found: {matched_keywords}

Email:
From: {sender}
To: {recipients}
Subject: {subject}
Date: {date}
Body:
{body_text}

Respond with this exact JSON structure:
{
  "summary": "2-3 sentence summary of the email content and any action items",
  "priority": <integer 1-5, where 5 is most urgent>,
  "categories": ["list", "of", "relevant", "tags"],
  "priority_reason": "One sentence explaining why you assigned this priority"
}
"""


@dataclass(frozen=True)
class AppConfig:
    vip_senders: list[str] = field(default_factory=list)
    skip_labels: list[str] = field(
        default_factory=lambda: [
            "CATEGORY_PROMOTIONS",
            "CATEGORY_SOCIAL",
            "CATEGORY_UPDATES",
        ]
    )
    priority_keywords: list[str] = field(
        default_factory=lambda: ["urgent", "deadline", "action required"]
    )
    digest_schedule: list[str] = field(
        default_factory=lambda: ["0 8 * * *", "0 13 * * *", "0 18 * * *"]
    )
    summarizer_schedule: list[str] = field(
        default_factory=lambda: ["0 8 * * *", "0 13 * * *", "0 18 * * *"]
    )
    ollama_model: str = "phi3:mini"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    gmail_max_results: int = 25
    summarizer_batch_size: int = 20
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE
    gmail_user_email: str = ""
    fetch_interval_minutes: int = 20
    ollama_url: str = "http://ollama:11434/api/generate"
    ollama_timeout_seconds: int = 180
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "0"
    prompt_body_max_chars: int = 6000


def _to_list(value: Any, fallback: list[str]) -> list[str]:
    if value is None:
        return fallback
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise ValueError(f"Expected list or string, got {type(value)!r}")


def load_config(config_path: str | None = None) -> AppConfig:
    resolved_path = Path(
        config_path
        or os.getenv("CONFIG_PATH")
        or "/config/config.yaml"
    )
    if not resolved_path.exists():
        fallback = Path("config/config.yaml")
        if fallback.exists():
            resolved_path = fallback
        else:
            raise FileNotFoundError(
                f"Config file not found at {resolved_path}. "
                "Create config/config.yaml from config/config.example.yaml."
            )

    raw_data = yaml.safe_load(resolved_path.read_text(encoding="utf-8")) or {}
    config = AppConfig(
        vip_senders=_to_list(raw_data.get("vip_senders"), []),
        skip_labels=_to_list(raw_data.get("skip_labels"), AppConfig().skip_labels),
        priority_keywords=_to_list(
            raw_data.get("priority_keywords"), AppConfig().priority_keywords
        ),
        digest_schedule=_to_list(
            raw_data.get("digest_schedule"), AppConfig().digest_schedule
        ),
        summarizer_schedule=_to_list(
            raw_data.get("summarizer_schedule"), AppConfig().summarizer_schedule
        ),
        ollama_model=str(raw_data.get("ollama_model", AppConfig().ollama_model)),
        telegram_bot_token=str(raw_data.get("telegram_bot_token", "")),
        telegram_chat_id=str(raw_data.get("telegram_chat_id", "")),
        gmail_max_results=int(
            raw_data.get("gmail_max_results", AppConfig().gmail_max_results)
        ),
        summarizer_batch_size=int(
            raw_data.get("summarizer_batch_size", AppConfig().summarizer_batch_size)
        ),
        prompt_template=str(
            raw_data.get("prompt_template", AppConfig().prompt_template)
        ),
        gmail_user_email=str(raw_data.get("gmail_user_email", "")),
        fetch_interval_minutes=int(
            raw_data.get("fetch_interval_minutes", AppConfig().fetch_interval_minutes)
        ),
        ollama_url=str(raw_data.get("ollama_url", AppConfig().ollama_url)),
        ollama_timeout_seconds=int(
            raw_data.get("ollama_timeout_seconds", AppConfig().ollama_timeout_seconds)
        ),
        ollama_num_ctx=int(raw_data.get("ollama_num_ctx", AppConfig().ollama_num_ctx)),
        ollama_keep_alive=str(raw_data.get("ollama_keep_alive", AppConfig().ollama_keep_alive)),
        prompt_body_max_chars=int(
            raw_data.get("prompt_body_max_chars", AppConfig().prompt_body_max_chars)
        ),
    )
    if config.gmail_max_results <= 0 or config.summarizer_batch_size <= 0:
        raise ValueError("gmail_max_results and summarizer_batch_size must be > 0")
    if config.ollama_timeout_seconds <= 0 or config.ollama_num_ctx <= 0 or config.prompt_body_max_chars <= 0:
        raise ValueError(
            "ollama_timeout_seconds, ollama_num_ctx, and prompt_body_max_chars must be > 0"
        )
    return config
