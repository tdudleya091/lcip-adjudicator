"""Browser fallback: serves web/ and the API on 127.0.0.1 only (never reachable from other machines)."""
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .paths import resource_dir

WEB = (resource_dir() / "web").resolve()


def make_handler(api):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            rel = self.path.split("?")[0].lstrip("/") or "index.html"
            path = (WEB / rel).resolve()
            if WEB not in path.parents or not path.is_file():
                return self.send_error(404)
            body = path.read_bytes()
            if path.name == "index.html":  # tell app.js to use fetch() instead of waiting for pywebview
                body = body.replace(b"<script src=\"app.js\">", b"<script>window.LCIP_BROWSER = true;</script><script src=\"app.js\">")
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            name = self.path.removeprefix("/api/")
            method = getattr(api, name, None)
            if name.startswith("_") or not callable(method):
                return self.send_error(404)
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"[]")
            body = json.dumps(method(*args)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return Handler


def serve(api, port=8642):
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(api))
