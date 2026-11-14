from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.quality import build_coverage_report, write_coverage_report

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and summarize collected F1 result data.")
    parser.add_argument("--data-dir", default="data/raw")
    args = parser.parse_args()
    report = build_coverage_report(args.data_dir)
    output = write_coverage_report(args.data_dir)
    print(json.dumps({"files_found": report["files_found"],
                      "coverage_rows": len(report["season_session_coverage"]),
                      "warnings": report["warnings"], "report_path": str(output)}, indent=2))
    print("\nSeason/session coverage:")
    for row in report["season_session_coverage"]:
        print(f"- {row['season']} {row['session']}: {row['rows']} rows, {row['events']} events, "
              f"{row['drivers']} drivers, {row['duplicate_event_driver_keys']} duplicate keys")
    print("\nStructural checks do not prove full source completeness or leakage safety.")

if __name__ == "__main__":
    main()
