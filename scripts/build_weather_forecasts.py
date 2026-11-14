"""Collect experimental F1 race-start weather forecasts (2022-2026 completed events).
Uses Open-Meteo Previous Runs API GFS Seamless *_previous_day1 fields.
Missing values are retained as blank/NaN; never substituted with zero/observations.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]  # script belongs in project/scripts/
PROCESSED = ROOT / "data" / "processed"
SCHEDULE = PROCESSED / "f1_session_schedule.csv"
COORDS = PROCESSED / "circuit_coordinates.csv"
OUTPUT = PROCESSED / "weather_forecasts_experimental.csv"
REPORT = ROOT / "reports" / "weather_collection_report.json"
API = "https://previous-runs-api.open-meteo.com/v1/forecast"
MODEL = "gfs_seamless"
SEASONS = {2022, 2023, 2024, 2025, 2026}
VARS = {
    "temperature_c": "temperature_2m_previous_day1",
    "relative_humidity_pct": "relative_humidity_2m_previous_day1",
    "precipitation_mm": "precipitation_previous_day1",
    "cloud_cover_pct": "cloud_cover_previous_day1",
    "wind_speed_kmh": "wind_speed_10m_previous_day1",
    "wind_direction_deg": "wind_direction_10m_previous_day1",
}


def race_circuit_map():
    files = sorted(PROCESSED.glob("*_race_normalized.csv"))
    if not files:
        raise FileNotFoundError(f"No *_race_normalized.csv files in {PROCESSED}")
    frames = []
    for path in files:
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception as exc:
            print(f"Skipping {path.name}: {exc}")
            continue
        if {"season", "round", "circuit_id"}.issubset(df.columns):
            frames.append(df[["season", "round", "circuit_id"]].drop_duplicates())
    if not frames:
        raise ValueError("Normalized race files need season, round, circuit_id columns")
    mapping = pd.concat(frames, ignore_index=True)
    mapping["season"] = pd.to_numeric(mapping["season"], errors="coerce")
    mapping["round"] = pd.to_numeric(mapping["round"], errors="coerce")
    mapping = mapping.dropna(subset=["season", "round", "circuit_id"])
    mapping[["season", "round"]] = mapping[["season", "round"]].astype(int)
    conflicts = mapping.groupby(["season", "round"])["circuit_id"].nunique()
    if (conflicts > 1).any():
        raise ValueError(f"Conflicting circuit IDs: {list(conflicts[conflicts > 1].index[:10])}")
    return mapping.drop_duplicates(["season", "round"])


def fetch(params, attempts=4):
    url = API + "?" + urlencode(params)
    last_error = None
    for attempt in range(attempts):
        req = Request(url, headers={"User-Agent": "F1-PredictLab/0.1 (research)", "Accept": "application/json"})
        try:
            with urlopen(req, timeout=35) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("API response was not a JSON object")
            return data
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code < 500 and exc.code != 429:
                break
            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Open-Meteo request failed: {last_error}")


def value_at_hour(times, values, target):
    target = target.floor("h")
    for i, stamp in enumerate(times or []):
        try:
            if pd.to_datetime(stamp, utc=True).floor("h") == target and i < len(values or []):
                return values[i]
        except Exception:
            continue
    return None


def main():
    if not SCHEDULE.exists() or not COORDS.exists():
        raise FileNotFoundError("Build f1_session_schedule.csv and circuit_coordinates.csv first")
    schedule = pd.read_csv(SCHEDULE)
    coords = pd.read_csv(COORDS)
    mapping = race_circuit_map()
    schedule["season"] = pd.to_numeric(schedule["season"], errors="coerce")
    schedule["round"] = pd.to_numeric(schedule["round"], errors="coerce")
    schedule = schedule[schedule["season"].isin(SEASONS)].copy()
    schedule[["season", "round"]] = schedule[["season", "round"]].astype(int)
    schedule["race_start_utc"] = pd.to_datetime(schedule["race_start_utc"], utc=True, errors="coerce")
    schedule = schedule.dropna(subset=["race_start_utc"])

    # Only collect completed events. The 24-hour buffer avoids treating a live
    # or just-finished session as a settled historical forecast record.
    completed_before = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24)
    schedule = schedule[schedule["race_start_utc"] < completed_before].copy()

    schedule = schedule.merge(mapping, on=["season", "round"], how="left", validate="one_to_one")
    for col in ["latitude", "longitude"]:
        coords[col] = pd.to_numeric(coords[col], errors="coerce")
    schedule = schedule.merge(coords[["circuit_id", "latitude", "longitude"]], on="circuit_id", how="left", validate="many_to_one")
    bad = schedule[schedule["circuit_id"].isna() | schedule["latitude"].isna() | schedule["longitude"].isna()]
    if not bad.empty:
        raise ValueError("Missing circuit mapping/coordinates:\n" + bad[["season", "round", "race_name"]].to_string(index=False))

    records = []
    races = schedule.sort_values(["season", "round"]).to_dict("records")
    for n, race in enumerate(races, 1):
        season = int(race["season"])
        race_start = pd.Timestamp(race["race_start_utc"])
        valid_hour = race_start.floor("h")
        selected = list(VARS.items()) if season >= 2024 else [("temperature_c", VARS["temperature_c"])]
        params = {
            "latitude": float(race["latitude"]), "longitude": float(race["longitude"]),
            "hourly": ",".join(api_name for _, api_name in selected),
            "models": MODEL, "timezone": "UTC", "start_date": valid_hour.strftime("%Y-%m-%d"),
            "end_date": valid_hour.strftime("%Y-%m-%d"), "temperature_unit": "celsius",
            "wind_speed_unit": "kmh", "precipitation_unit": "mm",
        }
        row = {
            "season": season, "round": int(race["round"]), "race_name": race["race_name"],
            "circuit_id": race["circuit_id"], "race_start_utc": race_start.isoformat(),
            "weather_valid_time_utc": valid_hour.isoformat(), "latitude": float(race["latitude"]),
            "longitude": float(race["longitude"]), "weather_source": "Open-Meteo Previous Runs API",
            "weather_model": MODEL, "forecast_lead_hours": 24,
            "forecast_field_suffix": "previous_day1",
            "weather_scope": "six_variables" if season >= 2024 else "temperature_only",
            "api_status": "ok", "api_error": None,
        }
        try:
            payload = fetch(params)
            hourly = payload.get("hourly") or {}
            times = hourly.get("time") or []
            for col, api_name in selected:
                row[col] = value_at_hour(times, hourly.get(api_name), valid_hour)
            if not times:
                row["api_status"] = "no_hourly_data"
        except Exception as exc:
            row["api_status"] = "error"
            row["api_error"] = str(exc)
            for col, _ in selected:
                row[col] = None
        for col in VARS:
            row.setdefault(col, None)
        records.append(row)
        print(f"[{n:02d}/{len(races)}] {season} R{int(race['round']):02d} {race['race_name']}: {row['api_status']} temp={row.get('temperature_c')}")
        time.sleep(0.15)

    result = pd.DataFrame(records).sort_values(["season", "round"])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, na_rep="")
    report = {
        "source": "Open-Meteo Previous Runs API", "documentation": "https://open-meteo.com/en/docs/previous-runs-api",
        "model": MODEL, "lead_time_definition": "previous_day1 is the value predicted 24 hours before valid time; it is a fixed lead-time offset, not one fixed initialization cycle.",
        "seasons": sorted(SEASONS), "total_races": int(len(result)),
        "successful_api_requests": int((result.api_status == "ok").sum()),
        "failed_or_empty_requests": int((result.api_status != "ok").sum()),
        "weather_non_null_counts": {c: int(result[c].notna().sum()) for c in VARS},
        "by_season": {}, "output_csv": str(OUTPUT.relative_to(ROOT)),
    }
    for season, group in result.groupby("season"):
        report["by_season"][str(int(season))] = {
            "races": int(len(group)), "successful_api_requests": int((group.api_status == "ok").sum()),
            "non_null_counts": {c: int(group[c].notna().sum()) for c in VARS},
        }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== WEATHER COLLECTION SUMMARY ===")
    print(f"CSV: {OUTPUT}\nReport: {REPORT}")
    print(f"Races: {len(result)} | successful requests: {report['successful_api_requests']}")
    print(result.groupby("season")[list(VARS)].count().to_string())
    print("Blank values mean unavailable data, not zero. previous_day1 is a 24-hour lead offset, not a fixed model-run timestamp.")
    print("Only events with scheduled race_start_utc at least 24 hours in the past were collected.")

if __name__ == "__main__":
    main()
