import hmac
import html
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


LOG = logging.getLogger(__name__)


def start_auth_server(schwab_client) -> None:
    port = int(os.getenv("PORT", "0") or 0)
    if not port:
        return
    setup_key = os.getenv("SCHWAB_AUTH_SETUP_KEY", "")
    broker_key = os.getenv("SCHWAB_TOKEN_BROKER_KEY", "")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/schwab-token":
                self.serve_broker_token()
                return
            if path != "/schwab-auth":
                self.send_error(404)
                return
            token_status = (
                "A stored Schwab token exists. Submitting this form replaces it."
                if os.path.exists(schwab_client.token_file)
                else "No stored Schwab token was found."
            )
            auth_url = html.escape(schwab_client.authorization_url(), quote=True)
            self.page(200, f"""
                <h1>Schwab authorization</h1>
                <p>{token_status}</p>
                <p><a href=\"{auth_url}\" target=\"_blank\">1. Sign in to Schwab</a></p>
                <p>2. Copy the complete <code>https://127.0.0.1/?code=...</code> URL from the browser.</p>
                <form method=\"post\" action=\"/schwab-auth\">
                    <label>Setup key<br><input type=\"password\" name=\"setup_key\" required></label><br><br>
                    <label>Complete redirected URL<br><textarea name=\"callback_url\" rows=\"5\" cols=\"80\" required></textarea></label><br><br>
                    <button type=\"submit\">Authorize immediately</button>
                </form>
            """)

        def do_POST(self):
            if urlparse(self.path).path != "/schwab-auth":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > 20_000:
                self.send_error(400)
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            supplied_key = form.get("setup_key", [""])[0]
            callback_url = form.get("callback_url", [""])[0]
            if not setup_key or not hmac.compare_digest(supplied_key, setup_key):
                self.page(403, "The setup key is missing or incorrect.")
                return
            try:
                schwab_client.exchange_callback_url(callback_url)
            except Exception as exc:
                LOG.warning("Schwab browser authorization failed: %s", exc)
                self.page(400, f"Authorization failed: {html.escape(str(exc))}")
                return
            self.page(200, "Schwab authorization succeeded. Delete SCHWAB_AUTH_SETUP_KEY and SCHWAB_AUTH_CALLBACK_URL from Railway.")

        def log_message(self, format, *args):
            LOG.info("Schwab auth page: " + format, *args)

        def serve_broker_token(self) -> None:
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {broker_key}"
            if not broker_key or not hmac.compare_digest(supplied, expected):
                self.json_response(401, {"error": "unauthorized"})
                return
            try:
                access_token = schwab_client.access_token()
            except Exception as exc:
                LOG.error("Schwab token broker unavailable: %s", type(exc).__name__)
                self.json_response(503, {"error": "token_unavailable"})
                return
            self.json_response(200, {"access_token": access_token, "expires_in": 240})

        def json_response(self, status: int, payload: dict) -> None:
            content = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def page(self, status: int, body: str) -> None:
            content = f"<!doctype html><html><head><meta charset=\"utf-8\"><title>Schwab authorization</title></head><body>{body}</body></html>".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, name="schwab-auth-server", daemon=True).start()
    LOG.info("Schwab authorization page available at /schwab-auth")
    if broker_key:
        LOG.info("Schwab token broker enabled at /schwab-token")
