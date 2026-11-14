from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
import argparse
import json
from pathlib import Path

from src.data.collectors import (
    collect_calendar,
    collect_season_results,
    collect_season_sprints,
    save_season_bundle,
)
from src.data.quality import inspect_directory


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect historical F1 race/qualifying/sprint results.")
    parser.add_argument("--start", type=int, default=2018, help="First season to collect (inclusive)")
    parser.add_argument("--end", type=int, default=2025, help="Last season to collect (inclusive)")
    parser.add_argument("--refresh", action="store_true", help="Ignore JSON cache and fetch again")
    parser.add_argument("--no-sprints", action="store_true", help="Skip sprint result endpoints")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--start must be <= --end")

    reports = []
    for season in range(args.start, args.end + 1):
        print(f"[{season}] Fetching calendar and session results...")
        calendar = collect_calendar(season, refresh=args.refresh)
        calendar_path = Path("data/raw") / f"{season}_calendar.json"
        calendar_path.parent.mkdir(parents=True, exist_ok=True)
        calendar_path.write_text(json.dumps(calendar, indent=2), encoding="utf-8")

        bundle = collect_season_results(season, refresh=args.refresh)
        if not args.no_sprints:
            sprint_bundle = collect_season_sprints(season, refresh=args.refresh)
            bundle["tables"].update(sprint_bundle["tables"])
            bundle["requests"].extend(sprint_bundle["requests"])
        saved = save_season_bundle(bundle)
        report = {
            "season": season,
            "events_in_calendar": len(calendar["events"]),
            "session_rows": {name: len(rows) for name, rows in bundle["tables"].items()},
            "saved": saved,
        }
        reports.append(report)
        print(json.dumps(report, indent=2))

    quality = inspect_directory("data/raw")
    Path("data/raw/data_quality_report.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
    print(f"Completed {len(reports)} seasons. Data-quality report: data/raw/data_quality_report.json")
    print("Note: these checks validate structure/duplicates/missingness, not model readiness or source completeness.")


if __name__ == "__main__":
    main()
