#!/usr/bin/env python3
"""Proxy server for Immich Face Fix tool. Serves static files and proxies API requests."""

import argparse
import http.server
import json
import os
import threading
import urllib.parse
import urllib.request
import urllib.error
import webbrowser


# .env variable names, in order of preference
URL_VARS = ("IMMICH_URL", "URL_IMMICH")
API_KEY_VARS = ("IMMICH_API_KEY",)
API_KEY_DEFAULT_VAR = API_KEY_VARS[0]

# Some Immich instances sit behind a CDN/WAF (e.g. Cloudflare) that rejects
# requests carrying urllib's default User-Agent, so send something normal.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def load_env_file(path):
    """Parse a simple KEY=VALUE .env file and return a dict.

    Supports blank lines, `#` comments, an optional `export ` prefix, and
    single- or double-quoted values. Missing files are ignored.
    """
    values = {}
    if not path or not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            else:
                # Strip trailing inline comment for unquoted values
                hash_pos = value.find(" #")
                if hash_pos != -1:
                    value = value[:hash_pos].rstrip()
            values[key] = value
    return values


def find_env_file(explicit):
    """Return the .env path to use: explicit flag, next to this script, or its parent."""
    if explicit:
        return explicit
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, ".env"),
        os.path.join(os.path.dirname(base_dir), ".env"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def first_set(mapping, names):
    for name in names:
        value = mapping.get(name)
        if value:
            return value
    return ""


def main():
    parser = argparse.ArgumentParser(description="Immich Face Fix proxy server")
    parser.add_argument("--immich-url", default=None,
                        help="Immich instance URL (e.g. https://photos.example.com)")
    parser.add_argument("--api-key", default=None,
                        help="Immich API key")
    parser.add_argument("--env-file", default=None,
                        help="Path to .env file (default: .env next to this script, "
                             "or in its parent directory)")
    parser.add_argument("--api-key-var", default=API_KEY_DEFAULT_VAR,
                        help=f".env variable holding the API key (default: {API_KEY_DEFAULT_VAR})")
    parser.add_argument("--url-var", default=URL_VARS[0],
                        help=f".env variable holding the Immich URL (default: {URL_VARS[0]})")
    parser.add_argument("--port", type=int, default=None,
                        help="Local port (default: 8080)")
    parser.add_argument("--host", default=None, help="Bind address (default: 127.0.0.1)")
    args = parser.parse_args()

    env_path = find_env_file(args.env_file)
    env = load_env_file(env_path)

    # Resolution order for each value: CLI flag > environment > .env file > built-in default.
    url_names = tuple(dict.fromkeys((args.url_var, *URL_VARS)))
    api_key_names = tuple(dict.fromkeys((args.api_key_var, *API_KEY_VARS)))
    immich_url = (
        args.immich_url
        or first_set(os.environ, url_names)
        or first_set(env, url_names)
    ).rstrip("/")
    api_key = (
        args.api_key
        or first_set(os.environ, api_key_names)
        or first_set(env, api_key_names)
    ).strip()
    port = (
        args.port
        or int(os.environ.get("PORT") or env.get("PORT") or "8080")
    )
    host = args.host or os.environ.get("HOST") or env.get("HOST") or "127.0.0.1"

    if not immich_url or not api_key:
        source = env_path or "no .env file found"
        parser.error(
            "--immich-url and --api-key are required "
            f"(looked for {'/'.join(url_names)} and "
            f"{'/'.join(api_key_names)} in {source})"
        )

    if env_path:
        print(f"Loaded configuration from {env_path}")

    # Quick connectivity check
    test_url = immich_url + "/api/server/about"
    test_req = urllib.request.Request(test_url)
    test_req.add_header("x-api-key", api_key)
    test_req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(test_req) as resp:
            print(f"Connected to Immich (status {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"WARNING: Immich returned {e.code} for {test_url}")
        print(f"  Check your --api-key value (length={len(api_key)}, starts with '{api_key[:4]}...')")
    except Exception as e:
        print(f"WARNING: Cannot reach Immich at {immich_url}: {e}")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    directory = dist_dir if os.path.isdir(dist_dir) else base_dir

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def end_headers(self):
            # Keep editors honest: never let the browser reuse a stale index.html.
            if not self.path.startswith("/api/"):
                self.send_header("Cache-Control", "no-store, max-age=0")
            super().end_headers()

        def do_GET(self):
            if not self._safe_request():
                return
            if self.path == "/api/_immich-url":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"url": immich_url}).encode())
            elif self.path.startswith("/api/"):
                self._proxy("GET")
            else:
                path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                relative = path.lstrip("/") or "index.html"
                parts = relative.split("/")
                allowed = (relative in ("index.html", "screenshot.png") if directory == base_dir
                           else all(p and not p.startswith(".") for p in parts)
                           and os.path.splitext(relative)[1].lower() in
                           (".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2"))
                resolved = os.path.realpath(os.path.join(directory, relative))
                if not allowed or not resolved.startswith(os.path.realpath(directory) + os.sep):
                    self.send_error(404)
                    return
                super().do_GET()

        def do_HEAD(self):
            self.send_error(405)

        def _safe_request(self):
            try:
                authority = urllib.parse.urlsplit("http://" + self.headers.get("Host", ""))
                valid_host = (authority.hostname in ("localhost", "127.0.0.1")
                              and authority.port == self.server.server_port)
            except ValueError:
                valid_host = False
            if host in ("127.0.0.1", "localhost") and not valid_host:
                self.send_error(403, "Invalid host")
                return False
            origin = self.headers.get("Origin")
            expected = "http://" + self.headers.get("Host", "")
            if (origin and origin != expected) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send_error(403, "Cross-origin request denied")
                return False
            if self.command != "GET" and self.headers.get("X-Face-Fix") != "1":
                self.send_error(403, "Missing request header")
                return False
            return True

        def do_PUT(self):
            self._proxy("PUT")

        def do_POST(self):
            self._proxy("POST")

        def do_DELETE(self):
            self._proxy("DELETE")

        def _proxy(self, method):
            if not self.path.startswith("/api/") or not self._safe_request():
                if not self.path.startswith("/api/"):
                    self.send_error(404)
                return
            target = immich_url + self.path
            body = None
            if method in ("PUT", "POST"):
                length = int(self.headers.get("Content-Length", 0))
                if length:
                    body = self.rfile.read(length)

            req = urllib.request.Request(target, data=body, method=method)
            req.add_header("x-api-key", api_key)
            req.add_header("User-Agent", USER_AGENT)
            if self.headers.get("Content-Type"):
                req.add_header("Content-Type", self.headers["Content-Type"])
            req.add_header("Accept", self.headers.get("Accept", "application/json"))

            try:
                with urllib.request.urlopen(req) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    for key in ("Content-Type", "Content-Length"):
                        val = resp.headers.get(key)
                        if val:
                            self.send_header(key, val)
                    self.end_headers()
                    self.wfile.write(resp_body)
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(e.read())
            except urllib.error.URLError as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        def log_message(self, fmt, *a):
            if a:
                print(f"  {' '.join(str(x) for x in a)}")

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: The proxy has no authentication; network clients can control the configured Immich account.")
    url = f"http://localhost:{port}/"
    print(f"Immich Face Fix running at {url}")
    print(f"Proxying to {immich_url}")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
