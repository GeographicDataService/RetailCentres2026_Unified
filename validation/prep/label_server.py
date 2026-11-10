"""Local labelling server for the audit sample. Every label is appended to labels.csv as it is made.

Run from repo root:  .venv/bin/python validation/prep/label_server.py [--labels PATH] [--port 8765]
Then open http://localhost:8765 in a browser.
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]  # validation/
AUDIT = HERE / "outputs/audit"
FIELDS = ["case_id", "stratum", "label", "notes", "paper_example", "labeller", "timestamp", "protocol_version"]
PROTOCOL_VERSION = "v1"


def read_labels(path):
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r["case_id"]: r for r in csv.DictReader(f)}  # latest row per case wins


def make_handler(labels_path, cases_path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body, ctype="application/json", code=200):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send((HERE / "label_tool.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/cases.geojson":
                self._send(cases_path.read_bytes())
            elif self.path == "/labels":
                self._send(json.dumps(read_labels(labels_path)))
            elif self.path == "/protocol":
                self._send((HERE / "audit" / "README.md").read_text(), "text/plain; charset=utf-8")
            else:
                self._send("not found", "text/plain", 404)

        def do_POST(self):
            if self.path != "/label":
                return self._send("not found", "text/plain", 404)
            rec = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if rec.get("label") not in ("yes", "no", "unsure"):
                return self._send('{"error": "label must be yes/no/unsure"}', code=400)
            row = {k: rec.get(k, "") for k in FIELDS}
            row["paper_example"] = int(bool(rec.get("paper_example")))
            row["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            row["protocol_version"] = PROTOCOL_VERSION
            new = not labels_path.exists()
            with open(labels_path, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)
            self._send(json.dumps(row))

        def log_message(self, *a):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=AUDIT / "labels.csv")
    ap.add_argument("--cases", type=Path, default=AUDIT / "cases.geojson")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    a.labels.parent.mkdir(parents=True, exist_ok=True)
    print(f"Labels -> {a.labels}\nOpen http://localhost:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.labels, a.cases)).serve_forever()


if __name__ == "__main__":
    main()
