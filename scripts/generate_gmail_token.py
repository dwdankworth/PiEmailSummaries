#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError as exc:
    raise SystemExit(
        "Missing dependency google-auth-oauthlib. "
        "Install with: pip install -r fetcher/requirements.txt"
    ) from exc

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Gmail OAuth token JSON for this project."
    )
    parser.add_argument(
        "--credentials",
        default="config/credentials.json",
        help="Path to OAuth client credentials JSON.",
    )
    parser.add_argument(
        "--token",
        default="config/token.json",
        help="Path to output OAuth token JSON.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local callback port for OAuth flow (0 = auto).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    credentials_path = Path(args.credentials)
    token_path = Path(args.token)

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Missing OAuth credentials file: {credentials_path}. "
            "Download it from Google Cloud Console first."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=args.port)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Wrote Gmail OAuth token to: {token_path}")


if __name__ == "__main__":
    main()
