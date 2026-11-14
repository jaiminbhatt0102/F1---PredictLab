"""Best-effort starting-grid collection.

The starting grid (with penalties) is only published by the results source once it
has the race entry. This stores it when available. If it is not there yet, nothing is
written and predictions fall back to the qualifying order, clearly labelled.

A grid can also be provided by hand: data/processed/<season>_starting_grid.csv with
the columns season,round,driver_id,grid.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.collectors import fetch_json


def fetch_starting_grid(season: int, round_no: int, output_dir: Path = Path("data/processed")) -> dict:
    payload = fetch_json(f"{season}/{round_no}/results.json?limit=100", refresh=True)
    races = (payload.get("MRData") or {}).get("RaceTable", {}).get("Races", [])
    rows = []
    for race in races:
        for result in race.get("Results", []):
            grid = result.get("grid")
            driver = (result.get("Driver") or {}).get("driverId")
            if driver and grid not in (None, ""):
                rows.append({"season": season, "round": round_no, "driver_id": driver, "grid": int(grid)})
    if not rows:
        return {"found": False, "rows": 0}
    path = Path(output_dir) / f"{season}_starting_grid.csv"
    new = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_csv(path)
        old = old[~((old["season"] == season) & (old["round"] == round_no))]
        new = pd.concat([old, new], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False)
    return {"found": True, "rows": len(rows)}
