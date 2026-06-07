import asyncio
import os
import urllib.parse

from google_auth_oauthlib.flow import Flow
from tinydb import TinyDB

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_PORT = int(os.getenv("PORT", os.getenv("OAUTH_REDIRECT_PORT", "8765")))
_PUBLIC_URL = os.getenv("PUBLIC_URL", f"http://localhost:{_PORT}").rstrip("/")
_REDIRECT_URI = f"{_PUBLIC_URL}/callback"

_AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", "data/auth.json")

_flow: Flow | None = None
_refresh_token: str | None = None
_server: asyncio.AbstractServer | None = None
_pending_future: asyncio.Future | None = None


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


async def _handle_callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global _pending_future, _flow, _refresh_token
    try:
        request_line = (await reader.readline()).decode(errors="replace")
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        parts = request_line.split()
        path = parts[1] if len(parts) >= 2 else "/"
        full_url = f"{_PUBLIC_URL}{path}"

        parsed = urllib.parse.urlparse(path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]

        if parsed.path in ("/health", "/"):
            response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nok"
            writer.write(response)
            await writer.drain()
            return

        if code and _flow and _pending_future and not _pending_future.done():
            try:
                _flow.fetch_token(authorization_response=full_url)
                token = _flow.credentials.refresh_token
                _refresh_token = token
                _save_token(token)
                _flow = None
                body = b"<html><body><h1>Autenticado. Puedes cerrar esta ventana.</h1></body></html>"
                _pending_future.set_result(None)
            except Exception as exc:
                body = f"<html><body><h1>Error: {exc}</h1></body></html>".encode()
                if not _pending_future.done():
                    _pending_future.set_exception(exc)
        else:
            body = b"<html><body><h1>No hay login en progreso.</h1></body></html>"

        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Connection: close\r\n\r\n"
        ) + body
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def start_callback_server() -> None:
    global _server
    _server = await asyncio.start_server(_handle_callback, "0.0.0.0", _PORT)


async def stop_callback_server() -> None:
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None


def generate_auth_url() -> str:
    global _flow, _pending_future
    if _pending_future and not _pending_future.done():
        raise RuntimeError("Ya hay un login en progreso.")
    loop = asyncio.get_running_loop()
    _pending_future = loop.create_future()
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


async def await_login_result(timeout: float = 300) -> None:
    if _pending_future is None:
        raise RuntimeError("No hay login en progreso.")
    try:
        await asyncio.wait_for(asyncio.shield(_pending_future), timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError("Tiempo de espera agotado. Intenta de nuevo con /login.")


def exchange_code(raw: str) -> None:
    """Fallback: accept the raw redirect URL or bare code (for local/manual use)."""
    global _flow, _refresh_token
    if _flow is None:
        raise RuntimeError("No hay login en progreso — envía /login primero.")
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
    if _pending_future and not _pending_future.done():
        _pending_future.set_result(None)
