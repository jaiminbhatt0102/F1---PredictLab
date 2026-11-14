"""Run one automation check, then exit. For Windows Task Scheduler.

    python scripts/run_automation.py

It does exactly what the API's built-in scheduler does every 15 minutes: looks at the
race calendar and runs whatever is due (data refresh, weather, predictions, retraining).
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.automation import run_tick


def main() -> None:
    results = run_tick()
    if not results:
        print("Nothing was due.")
    for r in results:
        print(f"[{r['status']}] {r['reason']}" + (f" - {r['error']}" if r.get("error") else ""))
    sys.exit(1 if any(r["status"] == "failed" for r in results) else 0)


if __name__ == "__main__":
    main()
