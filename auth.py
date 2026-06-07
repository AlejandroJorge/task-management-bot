import os
import urllib.parse

from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_REDIRECT_PORT = int(os.getenv("OAUTH_REDIRECT_PORT", "8765"))
_REDIRECT_URI = f"http://localhost:{_REDIRECT_PORT}/callback"

_flow: Flow | None = None
_refresh_token: str | None = None


def get_refresh_token() -> str | None:
    return _refresh_token


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
    Accept the full redirect URL (or bare code) copied from the browser.
    Stores the refresh token in memory only — lost on container restart.
    """
    global _flow, _refresh_token
    if _flow is None:
        raise RuntimeError("No login in progress — send /login first.")

    raw = raw.strip()
    parsed = urllib.parse.urlparse(raw)
    params = urllib.parse.parse_qs(parsed.query)

    if "code" in params and parsed.scheme:
        # Full redirect URL — pass it whole so the library handles state/PKCE
        _flow.fetch_token(authorization_response=raw)
    else:
        # Bare code value
        _flow.fetch_token(code=raw)

    _refresh_token = _flow.credentials.refresh_token
    _flow = None
