"""Child process for the production-startup test: imports `app:app` like a WSGI server and serves it."""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import app  # noqa: E402


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


server = make_server("127.0.0.1", 0, app, handler_class=Quiet)
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(1.5)
base = f"http://127.0.0.1:{server.server_port}"
print(json.dumps({"health": json.load(urllib.request.urlopen(base + "/api/health")),
                  "page_status": urllib.request.urlopen(base + "/").status}))
