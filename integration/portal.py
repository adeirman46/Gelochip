"""Local entry point for the three independently installed chip applications."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import urllib.request

SERVICES = {
    "gelochip": ("http://localhost:8090", "http://localhost:8090/api/health"),
    "anoa": ("http://localhost:5175", "http://localhost:8012/api/health"),
    "panda": ("http://localhost:8317", "http://localhost:8317/"),
}


def check_service(item):
    name, (url, health) = item
    try:
        with urllib.request.urlopen(health, timeout=2) as response:
            running = response.status == 200
    except Exception:
        running = False
    return name, {"url": url, "running": running}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/services":
            with ThreadPoolExecutor(max_workers=3) as pool:
                body = json.dumps(dict(pool.map(check_service, SERVICES.items()))).encode()
            content_type = "application/json"
        elif path in ("/", "/index.html"):
            body = Path(__file__).with_name("index.html").read_bytes()
            content_type = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Gelochip workspace: http://localhost:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
