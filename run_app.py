"""Start F1 PredictLab: one command, one address.

    python run_app.py

Finds a free port (so Windows' "port forbidden" error cannot stop it), starts the engine,
waits until it is ready, and opens the app in your browser.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANDIDATES = [8010, 8765, 5050, 7001, 8081, 9090]


def free_port(preferred: int | None) -> int:
    for port in ([preferred] if preferred else []) + CANDIDATES:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # let the system choose
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(url + "/health", timeout=1):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start F1 PredictLab")
    parser.add_argument("--port", type=int, default=None, help="preferred port (a free one is used if it is busy)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    try:
        import uvicorn
    except ImportError:
        print("The engine's libraries are missing. Run:  pip install -r requirements.txt")
        return 1
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("Note: the app screen is not built yet. Run:  cd frontend ; npm ci ; npm run build")
    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    print(f"\n  F1 PredictLab is starting at {url}\n  Leave this window open while you use the app. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("api.main:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
