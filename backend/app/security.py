"""A per-session key, so only the TidyByte page can use the local API.

The API can move and delete files, and it listens on localhost, where any
web page you visit could try to send it requests. So:

- A random key is made each time the backend starts.
- Only the TidyByte page can fetch it (GET /api/session checks the Origin
  header, which browsers set and pages can't fake), and only when the
  request was addressed to localhost, which defeats DNS rebinding.
- Every other request must carry it in the X-TidyByte-Token header. A
  custom header also forces the browser to ask (CORS preflight) before
  sending anything cross-site.

A program already running as you could imitate the page; nothing short of
the operating system can stop that, and such a program could delete your
files directly anyway. This keeps out web pages and casual local callers.
"""
import os
import secrets

from fastapi import HTTPException, Request

HEADER = "X-TidyByte-Token"

TOKEN = secrets.token_urlsafe(32)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def allowed_origins() -> list[str]:
    configured = os.getenv("TIDYBYTE_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _check_host(request: Request) -> None:
    host = request.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    if hostname.lower() not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="TidyByte only answers on localhost.")


def session_token(request: Request) -> str:
    """The key, for the TidyByte page only."""
    _check_host(request)
    if request.headers.get("origin") not in allowed_origins():
        raise HTTPException(status_code=403, detail="Only the TidyByte page can start a session.")
    return TOKEN


def require_session(request: Request) -> None:
    _check_host(request)
    given = request.headers.get(HEADER, "")
    # <img> tags can't send headers, so thumbnails take it in the URL.
    if not given and request.url.path.endswith("/thumbnail"):
        given = request.query_params.get("token", "")
    if not secrets.compare_digest(given.encode(), TOKEN.encode()):
        raise HTTPException(
            status_code=401,
            detail="Missing or outdated session key. Reload the page.",
        )
