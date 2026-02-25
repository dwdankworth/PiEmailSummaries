from __future__ import annotations

import base64
import os
import socket
import tempfile
import time
from email.utils import parseaddr
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from common.logging_utils import get_logger

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
LOGGER = get_logger("fetcher")
_GMAIL_MAX_RETRIES = 3


def _execute_with_retry(request, description: str = "Gmail API call"):
    """Execute a Google API request with retry logic for transient errors."""
    last_error: Exception | None = None
    for attempt in range(1, _GMAIL_MAX_RETRIES + 1):
        try:
            return request.execute(num_retries=2)
        except HttpError as exc:
            last_error = exc
            if exc.resp.status < 500:
                raise  # Don't retry client errors
            LOGGER.warning(
                "%s failed (HTTP %s), retrying",
                description,
                exc.resp.status,
                extra={"extra_json": {"attempt": attempt, "error": str(exc)}},
            )
        except (socket.timeout, OSError) as exc:
            last_error = exc
            LOGGER.warning(
                "%s network error, retrying",
                description,
                extra={"extra_json": {"attempt": attempt, "error": str(exc)}},
            )
        if attempt < _GMAIL_MAX_RETRIES:
            time.sleep(1.0 * (2 ** (attempt - 1)))
    raise last_error  # type: ignore[misc]


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
        # Write token back.  We try atomic rename first, but fall back to
        # in-place write when the path is a Docker bind-mounted file (rename
        # across mount points raises EBUSY).
        dir_name = os.path.dirname(token_path)
        token_json = credentials.to_json()
        try:
            fd = tempfile.NamedTemporaryFile(
                mode='w',
                dir=dir_name,
                delete=False,
                suffix='.tmp',
                encoding='utf-8',
            )
            try:
                fd.write(token_json)
                fd.flush()
                os.fsync(fd.fileno())
                fd.close()
                os.chmod(fd.name, 0o600)
                os.replace(fd.name, token_path)
            except BaseException:
                fd.close()
                try:
                    os.unlink(fd.name)
                except OSError:
                    pass
                raise
        except OSError:
            # Fallback: write directly (bind-mounted file)
            with open(token_path, 'w', encoding='utf-8') as f:
                f.write(token_json)
                f.flush()
                os.fsync(f.fileno())

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_recent_messages(service: Resource, max_results: int) -> list[dict[str, Any]]:
    response = _execute_with_retry(
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, includeSpamTrash=False),
        description="messages.list",
    )
    messages = response.get("messages", [])
    output: list[dict[str, Any]] = []
    for message_ref in messages:
        message = _execute_with_retry(
            service.users()
            .messages()
            .get(userId="me", id=message_ref["id"], format="full"),
            description=f"messages.get({message_ref['id']})",
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
