"""Game of Claude (Claude telemetry dashboard): serves index.html and pushes live updates from the local transcripts.

    python3 server.py                      # http://127.0.0.1:8765
    python3 server.py --port 9000 --days 60
    python3 server.py --export report.html # static one-file snapshot, no server needed
    python3 server.py --ledger /tmp/l.json # XP ledger elsewhere (default: env CLAUDE_TELEMETRY_LEDGER
                                           # or $XDG_DATA_HOME/claude-telemetry/ledger.json)
    python3 server.py --new-game           # hero back to level 1, old ledger kept as a backup

A watcher thread checks the transcripts every --interval seconds (only appended bytes are
parsed) and pushes a new snapshot via Server-Sent Events (/api/events) only when something
changed, including status changes without new records (e.g. "approval?" after 30 s).
The game counts only what happened since its start (first run or --new-game). The XP ledger
(ledger.py) keeps the start and the XP of deleted transcripts; it is written at most every
30 s while something changes, and on exit.
"""
from __future__ import annotations

import argparse
import json
import signal
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import insights
import ledger
from collect import PROJECTS_DIR, Collector

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"
STATIC = {"/game.js": (HERE / "game.js", "text/javascript; charset=utf-8")}
KEEPALIVE = 15  # seconds between SSE comments, keeps proxies and the browser from closing idle streams
STALE = 60  # seconds after which a snapshot is rebuilt even without changes


class Hub:
    """Owns the collector (the watcher thread, and on exit the main thread, under self.lock)
    and the latest snapshot."""

    def __init__(self, root: Path, days: int, ledger_path: Path | None = ledger.PATH):
        self.collector, self.days = Collector(root, ledger_path), days
        self.lock = threading.Lock()
        self.cond = threading.Condition()
        self.version, self.data = 0, b"{}"
        self.ins_run = {"running": False, "startedAt": None, "error": None}  # dashboard-triggered insights run

    def refresh_insights(self, root: Path) -> bool:
        """Re-runs insights.py with the Claude review in the background (one run at a time).
        False if a run is already going."""
        with self.cond:
            if self.ins_run["running"]:
                return False
            self.ins_run = {"running": True, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "error": None}

        def work():
            error = None
            try:
                report = insights.run(insights.DAYS, root, True, insights.CLAUDE_MODEL)
                insights.save(report)
                if not report["review"]["ok"]:
                    error = report["review"]["error"]
            except Exception as e:  # shown in the card, the server keeps running
                error = repr(e)[:300]
            with self.cond:
                self.ins_run = {"running": False, "startedAt": None, "error": error}
            with self.lock:
                self.build()

        threading.Thread(target=work, daemon=True).start()
        with self.lock:
            self.build()
        return True

    def build(self):
        snap = self.collector.snapshot(self.days, refresh=False)
        snap["insights"] = insights.latest()  # newest insights.py report, picked up within STALE seconds
        snap["insightsRun"] = self.ins_run
        data = json.dumps(snap, default=str).encode()
        with self.cond:
            self.version += 1
            self.data = data
            self.cond.notify_all()

    def watch(self, interval: float):
        sig, built = self.collector.attention_sig(), time.monotonic()
        while True:
            time.sleep(interval)
            try:
                with self.lock:
                    changed = self.collector.refresh()
                    new_sig = self.collector.attention_sig()
                    # also rebuild once a minute: "active now" and the day change are time-based
                    if changed or new_sig != sig or time.monotonic() - built > STALE:
                        sig, built = new_sig, time.monotonic()
                        self.build()
                    self.collector.save()  # throttled, no-op without changes
            except Exception as e:  # keep watching, a single bad file must not stop the stream
                print(f"watch error: {e!r}")

    def wait(self, seen: int, timeout: float) -> tuple[int, bytes]:
        with self.cond:
            self.cond.wait_for(lambda: self.version != seen, timeout)
            return self.version, self.data


def handler(hub: Hub, root: Path):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            # The custom header makes a cross-site request need a CORS preflight, which this server
            # never answers, so other web pages cannot start (paid) Claude runs via localhost.
            if self.path != "/api/insights/refresh" or self.headers.get("X-Game-Of-Claude") != "1":
                return self._send(404, "text/plain", b"not found")
            started = hub.refresh_insights(root)
            self._send(202 if started else 409, "application/json", json.dumps({"started": started}).encode())

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", INDEX.read_bytes())
            elif path in STATIC:
                f, ctype = STATIC[path]
                self._send(200, ctype, f.read_bytes())
            elif path == "/api/stats":
                self._send(200, "application/json", hub.data)
            elif path == "/api/events":
                self._stream()
            elif path == "/healthz":
                self._send(200, "text/plain", b"ok")
            else:
                self._send(404, "text/plain", b"not found")

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            seen = 0
            try:
                self.wfile.write(b"retry: 2000\n\n")
                while True:
                    version, data = hub.wait(seen, KEEPALIVE)
                    if version != seen:
                        seen = version
                        self.wfile.write(b"id: %d\ndata: %s\n\n" % (version, data))
                    else:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # tab closed

        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):  # quiet
            pass

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--days", type=int, default=30, help="days shown in the activity chart")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between transcript checks")
    ap.add_argument("--projects-dir", type=Path, default=PROJECTS_DIR, help="Claude Code transcripts")
    ap.add_argument("--export", type=Path, metavar="FILE", help="write a static HTML snapshot and exit")
    ap.add_argument("--ledger", type=Path, default=ledger.PATH,
                    help=f"XP ledger that keeps the XP of deleted transcripts (default: {ledger.PATH})")
    ap.add_argument("--new-game", action="store_true", help="start the game over at level 1 (backs up the old ledger)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    hub = Hub(args.projects_dir, args.days, args.ledger)
    if args.new_game:
        hub.collector.new_game()
        print(f"new game: level 1 from {hub.collector.start:%Y-%m-%d %H:%M}", flush=True)
    print(f"reading {args.projects_dir} …", flush=True)
    t0 = time.perf_counter()
    hub.collector.refresh()
    hub.build()
    hub.collector.save(force=True)
    print(f"parsed {len(hub.collector.cache)} transcripts in {time.perf_counter() - t0:.1f}s, "
          f"{len(hub.collector.archived())} archived in {args.ledger}", flush=True)

    if args.export:
        data = hub.data.decode().replace("</", "<\\/")
        html = INDEX.read_text(encoding="utf-8").replace("/*__SNAPSHOT__*/null", data)
        for name, (f, _) in STATIC.items():  # one self-contained file
            js = f.read_text(encoding="utf-8").replace("</", "<\\/")
            html = html.replace(f'<script src="{name[1:]}"></script>', f"<script>{js}</script>")
        args.export.write_text(html, encoding="utf-8")
        print(f"wrote {args.export}")
        return

    threading.Thread(target=hub.watch, args=(args.interval,), daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), handler(hub, args.projects_dir))
    srv.daemon_threads = True  # open SSE streams must not block Ctrl+C
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}/"
    print(f"Game of Claude on {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()

    def stop(*_):
        raise KeyboardInterrupt  # SIGTERM: same clean exit as Ctrl+C

    signal.signal(signal.SIGTERM, stop)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if hub.lock.acquire(timeout=5) and hub.collector.save(force=True):  # let a running refresh finish
            print(f"saved {args.ledger}", flush=True)


if __name__ == "__main__":
    main()
