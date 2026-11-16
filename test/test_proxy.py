import http.server
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Upstream(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class ProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=cls.upstream.serve_forever, daemon=True).start()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.process = subprocess.Popen(
            [sys.executable, str(ROOT / "serve.py"), "--immich-url",
             f"http://127.0.0.1:{cls.upstream.server_port}", "--api-key", "test",
             "--port", str(cls.port), "--host", "127.0.0.1"],
            env={**os.environ, "BROWSER": "true"}, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                with urllib.request.urlopen(cls.base + "/", timeout=0.2):
                    return
            except urllib.error.URLError:
                time.sleep(0.05)
        raise RuntimeError("proxy did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.upstream.shutdown()
        cls.upstream.server_close()

    def request(self, path, method="GET", headers=None):
        req = urllib.request.Request(self.base + path, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def test_static_files_are_restricted(self):
        self.assertEqual(self.request("/"), 200)
        for path in ("/.env", "/serve.py", "/%2eenv", "/.git/config"):
            self.assertEqual(self.request(path), 404)

    def test_mutations_require_same_origin_and_header(self):
        self.assertEqual(self.request("/api/people", "POST"), 403)
        self.assertEqual(self.request("/api/people", "POST", {
            "X-Face-Fix": "1", "Origin": "https://attacker.example",
        }), 403)
        self.assertEqual(self.request("/api/people", "POST", {
            "X-Face-Fix": "1", "Origin": self.base,
        }), 200)
        self.assertEqual(self.request("/elsewhere", "POST", {"X-Face-Fix": "1"}), 404)
        self.assertEqual(self.request("/api/people", headers={"Host": f"attacker.example:{self.port}"}), 403)


if __name__ == "__main__":
    unittest.main()
