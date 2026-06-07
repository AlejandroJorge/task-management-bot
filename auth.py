import os
import urllib.parse

from google_auth_oauthlib.flow import Flow
from tinydb import TinyDB

# oauthlib requires HTTPS by default; localhost redirects are always safe
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_REDIRECT_PORT = int(os.getenv("OAUTH_REDIRECT_PORT", "8765"))
_REDIRECT_URI = f"http://localhost:{_REDIRECT_PORT}/callback"
_AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", "auth.json")

_flow: Flow | None = None
_refresh_token: str | None = None


def _auth_db() -> TinyDB:
    return TinyDB(_AUTH_DB_PATH)


def get_refresh_token() -> str | None:
    return _refresh_token


def load_saved_token() -> bool:
    """Load persisted refresh token from DB into memory. Returns True if found."""
    global _refresh_token
    with _auth_db() as db:
        row = db.get(doc_id=1)
    if row and row.get("refresh_token"):
        _refresh_token = row["refresh_token"]
        return True
    return False


def _save_token(token: str) -> None:
    with _auth_db() as db:
        if db.get(doc_id=1):
            db.update({"refresh_token": token}, doc_ids=[1])
        else:
            db.insert({"refresh_token": token})


def clear_token() -> None:
    """Remove token from memory and DB (call when credentials are revoked)."""
    global _refresh_token
    _refresh_token = None
    with _auth_db() as db:
        db.truncate()


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
    Stores the refresh token in memory and persists it to DB.
    """
    global _flow, _refresh_token
    if _flow is None:
        raise RuntimeError("No login in progress — send /login first.")

    raw = raw.strip()
    parsed = urllib.parse.urlparse(raw)
    params = urllib.parse.parse_qs(parsed.query)

    if "code" in params and parsed.scheme:
        _flow.fetch_token(authorization_response=raw)
    else:
        _flow.fetch_token(code=raw)

    _refresh_token = _flow.credentials.refresh_token
    _save_token(_refresh_token)
    _flow = None
