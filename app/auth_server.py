import hmac
import html
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

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path != "/schwab-auth":
                self.send_error(404)
                return
            if os.path.exists(schwab_client.token_file):
                self.page(200, "Schwab is already authorized. You can remove SCHWAB_AUTH_SETUP_KEY from Railway.")
                return
            auth_url = html.escape(schwab_client.authorization_url(), quote=True)
            self.page(200, f"""
                <h1>Schwab authorization</h1>
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
