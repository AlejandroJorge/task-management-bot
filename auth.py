import os
import urllib.parse
from pathlib import Path

from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_REDIRECT_PORT = int(os.getenv("OAUTH_REDIRECT_PORT", "8765"))
_REDIRECT_URI = f"http://localhost:{_REDIRECT_PORT}/callback"

_flow: Flow | None = None


def generate_auth_url() -> str:
    """Create a new OAuth flow and return the Google auth URL."""
    global _flow
    _flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uris": [_REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=_REDIRECT_URI,
    )
    url, _ = _flow.authorization_url(access_type="offline", prompt="consent")
    return url


def exchange_code(raw: str) -> None:
    """
    Accept the full redirect URL (or just the bare code) that the user
    copies from their browser after approving access. Parses all query
    params robustly so extra params don't cause issues.

    Updates GOOGLE_REFRESH_TOKEN in os.environ and rewrites .env in place.
    """
    global _flow
    if _flow is None:
        raise RuntimeError("No login in progress — send /login first.")

    # Robustly extract code= regardless of what else is in the query string
    parsed = urllib.parse.urlparse(raw.strip())
    params = urllib.parse.parse_qs(parsed.query)

    if "code" in params:
        code = params["code"][0]
    else:
        # User pasted just the bare code value
        code = raw.strip()

    _flow.fetch_token(code=code)
    refresh_token = _flow.credentials.refresh_token
    _flow = None

    os.environ["GOOGLE_REFRESH_TOKEN"] = refresh_token
    _write_env("GOOGLE_REFRESH_TOKEN", refresh_token)


def _write_env(key: str, value: str) -> None:
    """Update or append a key=value line in .env without touching other lines."""
    env_path = Path(".env")
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n")
        return

    lines = env_path.read_text().splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")
