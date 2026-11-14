"""CLI: python scripts/fetch_starting_grid.py --season 2026 --round 18"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.grid import fetch_starting_grid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", dest="round_no", type=int, required=True)
    args = parser.parse_args()
    result = fetch_starting_grid(args.season, args.round_no)
    print("Starting grid found." if result["found"] else "Starting grid not published yet; qualifying order will be used.")


if __name__ == "__main__":
    main()
