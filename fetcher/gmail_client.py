from __future__ import annotations

import base64
import os
from email.utils import parseaddr
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _decode_body(payload: dict[str, Any]) -> str:
    def _decode_data(data: str) -> str:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode(
            "utf-8", errors="replace"
        )

    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            body = part.get("body", {})
            if mime_type == "text/plain" and "data" in body:
                return _decode_data(body["data"])
        for part in payload["parts"]:
            body = _decode_body(part)
            if body.strip():
                return body
    body_data = payload.get("body", {}).get("data")
    if body_data:
        return _decode_data(body_data)
    return ""


def _headers_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers", [])
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in headers
        if item.get("name")
    }


def build_gmail_service() -> Resource:
    token_path = os.getenv("GMAIL_TOKEN_PATH", "/secrets/token.json")
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "/secrets/credentials.json")

    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"Missing Gmail OAuth token file at {token_path}. "
            "Create it on the host and bind mount it."
        )
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Missing Gmail OAuth credentials file at {credentials_path}. "
            "Create it in Google Cloud Console and bind mount it."
        )

    credentials = Credentials.from_authorized_user_file(token_path, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(credentials.to_json())

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_recent_messages(service: Resource, max_results: int) -> list[dict[str, Any]]:
    response = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, includeSpamTrash=False)
        .execute()
    )
    messages = response.get("messages", [])
    output: list[dict[str, Any]] = []
    for message_ref in messages:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_ref["id"], format="full")
            .execute()
        )
        payload = message.get("payload", {})
        headers = _headers_map(payload)
        sender = headers.get("from", "")
        output.append(
            {
                "gmail_id": str(message.get("id", "")),
                "thread_id": str(message.get("threadId", "")),
                "sender": sender,
                "sender_email": parseaddr(sender)[1].lower(),
                "recipients": headers.get("to", ""),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "label_ids": [str(label) for label in message.get("labelIds", [])],
                "headers": headers,
                "body_text": _decode_body(payload) or str(message.get("snippet", "")),
            }
        )
    return output
