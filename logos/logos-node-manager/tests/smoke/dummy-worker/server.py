"""A stand-in for the worker node, for the smoke test.

It answers on port 80 like the worker does, and it can be built as a broken release that stops at once.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

VERSION = os.environ.get("WORKER_VERSION", "dev")
MODE = os.environ.get("WORKER_MODE", "good")

if MODE == "broken":
    print("dummy worker: broken build, cannot start", flush=True)
    sys.exit(1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"service": "DummyWorker", "version": VERSION}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


print(f"dummy worker {VERSION} is listening on port 80", flush=True)
HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
