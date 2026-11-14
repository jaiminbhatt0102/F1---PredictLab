"""Data-quality and coverage reporting for normalized historical F1 result tables."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import pandas as pd

KEY_COLUMNS = ["season", "round", "driver_id"]


def _read_csv_or_empty(path: str | Path) -> pd.DataFrame:
    """Read a CSV safely, including intentionally empty result files."""
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

def inspect_csv(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    frame = _read_csv_or_empty(path)
    missing_key_columns = [c for c in KEY_COLUMNS if c not in frame.columns]
    duplicate_keys = None if missing_key_columns else int(frame.duplicated(KEY_COLUMNS).sum())
    return {
        "file": str(path), "rows": int(len(frame)), "columns_count": int(len(frame.columns)),
        "columns": list(frame.columns), "missing_key_columns": missing_key_columns,
        "duplicate_event_driver_keys": duplicate_keys,
        "missing_by_column": {str(k): int(v) for k, v in frame.isna().sum().items()},
        "empty": bool(frame.empty),
    }

def build_coverage_report(directory: str | Path = "data/raw") -> dict[str, Any]:
    base = Path(directory)
    files = sorted(base.glob("*_results.csv"))
    inspections = [inspect_csv(p) for p in files]
    coverage = []
    for path in files:
        frame = _read_csv_or_empty(path)
        parts = path.name.split("_")
        season, session = (parts[0], parts[1]) if len(parts) > 1 else ("unknown", "unknown")
        keys = {"season", "round", "driver_id"}
        coverage.append({
            "season": season, "session": session, "file": path.name, "rows": int(len(frame)),
            "events": int(frame[["season", "round"]].drop_duplicates().shape[0])
                if {"season", "round"}.issubset(frame.columns) else None,
            "drivers": int(frame["driver_id"].nunique()) if "driver_id" in frame.columns else None,
            "duplicate_event_driver_keys": int(frame.duplicated(KEY_COLUMNS).sum())
                if keys.issubset(frame.columns) else None,
        })
    warnings = []
    if not files:
        warnings.append("No *_results.csv files found. Run scripts/collect_f1_data.py first.")
    if files and not any("_race_" in p.name for p in files):
        warnings.append("No race results file found.")
    if files and not any("_qualifying_" in p.name for p in files):
        warnings.append("No qualifying results file found.")
    if files and not any("_sprint_" in p.name for p in files):
        warnings.append("No sprint results file found; this may be normal for seasons without sprint events.")
    for item in inspections:
        if item["missing_key_columns"]:
            warnings.append(f"{item['file']}: missing key columns {item['missing_key_columns']}")
        if item["duplicate_event_driver_keys"]:
            warnings.append(f"{item['file']}: {item['duplicate_event_driver_keys']} duplicate event-driver keys")
        if item["empty"]:
            warnings.append(f"{item['file']}: file has no rows")
    return {"directory": str(base), "files_found": len(files), "file_inspections": inspections,
            "season_session_coverage": coverage, "warnings": warnings}

def write_coverage_report(directory: str | Path = "data/raw") -> Path:
    report = build_coverage_report(directory)
    output = Path(directory) / "data_coverage_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return output


def inspect_directory(directory: str | Path = "data/raw") -> dict[str, Any]:
    """Inspect all CSV files in a directory and return a coverage report."""
    return build_coverage_report(directory)
