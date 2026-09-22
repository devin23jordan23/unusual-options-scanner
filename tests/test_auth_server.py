import json
import os
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import Mock, patch

from app.auth_server import start_auth_server


class AuthServerTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.token_file = "/tmp/nonexistent-schwab-token"
        self.client.access_token.return_value = "short-lived-token"
        self.client.authorization_url.return_value = "https://example.test/auth"

    def request(self, headers=None):
        server = self.server
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("GET", "/schwab-token", headers=headers or {})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def test_broker_requires_shared_key_and_never_exposes_refresh_token(self):
        with patch.dict(os.environ, {"PORT": "0", "SCHWAB_TOKEN_BROKER_KEY": "shared-secret"}, clear=False):
            from app import auth_server
            original_server = auth_server.ThreadingHTTPServer

            def capture_server(address, handler):
                self.server = original_server((address[0], 0), handler)
                return self.server

            with patch.object(auth_server, "ThreadingHTTPServer", side_effect=capture_server):
                with patch.dict(os.environ, {"PORT": "1"}):
                    start_auth_server(self.client)

            status, body = self.request()
            self.assertEqual((status, body), (401, {"error": "unauthorized"}))
            status, body = self.request({"Authorization": "Bearer shared-secret"})
            self.assertEqual(status, 200)
            self.assertEqual(body, {"access_token": "short-lived-token", "expires_in": 240})
            self.assertNotIn("refresh_token", body)
            self.server.shutdown()
            self.server.server_close()


if __name__ == "__main__":
    unittest.main()
