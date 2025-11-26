# Helper to generate Gmail OAuth token.json for sending emails via Gmail API
# Usage:
#   1) Place credentials.json in the same folder (or set env GMAIL_CREDENTIALS_JSON)
#   2) Ensure your .env has GMAIL_TOKEN_JSON (default: token.json)
#   3) Run: .venv/bin/python gen_gmail_token.py

import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials  # type: ignore

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main():
    creds_path = Path(os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")).resolve()
    token_path = Path(os.getenv("GMAIL_TOKEN_JSON", "token.json")).resolve()

    if not creds_path.exists():
        print(f"credentials.json not found at: {creds_path}")
        print("Download it from Google Cloud Console (OAuth Client - Desktop App) and place it here.")
        return

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            creds = None

    try:
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Try to open a local browser; if headless, fall back to console
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception:
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                    creds = flow.run_console()
            token_path.write_text(creds.to_json(), encoding="utf-8")
            print(f"Wrote token to {token_path}")
        else:
            print("token.json already valid")
    except Exception as e:
        print(f"Error during OAuth: {e}")


if __name__ == "__main__":
    main()
