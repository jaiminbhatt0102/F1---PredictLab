"""Fetch immutable pre-race forecast snapshots and post-race archive weather.

Examples:
  python scripts/fetch_event_weather.py forecast --season 2026 --round 18
  python scripts/fetch_event_weather.py observed --season 2026 --round 18

Forecast snapshots are saved separately from historical archive data. The archive
endpoint provides historical gridded/reanalysis data, not guaranteed circuit-station
observations; its source is explicitly labelled.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
SCHEDULE_PATH = PROCESSED / "f1_session_schedule.csv"
COORDS_PATH = PROCESSED / "circuit_coordinates.csv"

FORECAST_PATH = PROCESSED / "weather_forecast_snapshots.csv"
OBSERVED_PATH = PROCESSED / "weather_historical_archive.csv"
REPORT_DIR = ROOT / "reports"

FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"

VARIABLES = {
    "temperature_c": "temperature_2m",
    "relative_humidity_pct": "relative_humidity_2m",
    "precipitation_mm": "precipitation",
    "cloud_cover_pct": "cloud_cover",
    "wind_speed_kmh": "wind_speed_10m",
    "wind_direction_deg": "wind_direction_10m",
}


def request_json(url: str, attempts: int = 4) -> dict:
    last_error = None
    for attempt in range(attempts):
        req = Request(
            url,
            headers={
                "User-Agent": "F1-PredictLab/0.1 (research project)",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("API response was not a JSON object")
            if payload.get("error"):
                raise RuntimeError(str(payload.get("reason", payload["error"])))
            return payload
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code < 500 and exc.code != 429:
                break
            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Weather API request failed: {last_error}")


def load_event(season: int, round_no: int) -> dict:
    if not SCHEDULE_PATH.exists() or not COORDS_PATH.exists():
        raise FileNotFoundError(
            "Required files missing: data/processed/f1_session_schedule.csv "
            "and/or circuit_coordinates.csv"
        )

    schedule = pd.read_csv(SCHEDULE_PATH, dtype={"locality": "string"})
    schedule["season"] = pd.to_numeric(schedule["season"], errors="coerce")
    schedule["round"] = pd.to_numeric(schedule["round"], errors="coerce")
    matches = schedule.loc[
        (schedule["season"] == season) & (schedule["round"] == round_no)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one schedule row for {season} round {round_no}; found {len(matches)}"
        )
    event = matches.iloc[0].to_dict()
    event["race_start_utc"] = pd.to_datetime(event["race_start_utc"], utc=True, errors="coerce")
    if pd.isna(event["race_start_utc"]):
        raise ValueError("Schedule row has no valid race_start_utc")

    coords = pd.read_csv(COORDS_PATH)
    for col in ("latitude", "longitude"):
        coords[col] = pd.to_numeric(coords[col], errors="coerce")
    coords = coords.dropna(subset=["latitude", "longitude"])

    # First try matching schedule locality to the verified circuit coordinate locality.
    locality = str(event.get("locality", "")).strip().casefold()
    candidates = coords.loc[
        coords["locality"].astype("string").str.strip().str.casefold() == locality
    ]

    # A locality match must be unique; ambiguous mapping should be fixed in the data,
    # not silently guessed.
    if len(candidates) != 1:
        raise ValueError(
            f"Could not uniquely map schedule locality {event.get('locality')!r} "
            f"to circuit_coordinates.csv (matches={len(candidates)}). "
            "Add/verify an explicit circuit mapping before fetching weather."
        )
    coord = candidates.iloc[0].to_dict()
    if not bool(coord.get("verified", False)):
        raise ValueError(f"Coordinates for {coord.get('circuit_id')} are not verified")

    event.update({
        "circuit_id": str(coord["circuit_id"]).strip(),
        "circuit_name": str(coord["circuit_name"]).strip(),
        "latitude": float(coord["latitude"]),
        "longitude": float(coord["longitude"]),
    })
    return event


def get_hourly_value(payload: dict, api_variable: str, valid_time: pd.Timestamp):
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get(api_variable) or []
    target = valid_time.floor("h")
    for i, stamp in enumerate(times):
        try:
            if pd.to_datetime(stamp, utc=True).floor("h") == target:
                return values[i] if i < len(values) else None
        except Exception:
            continue
    return None


def append_immutable(path: Path, row: dict, identity_cols: list[str]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([row])
    if path.exists():
        old = pd.read_csv(path, low_memory=False)
        # Prevent exact duplicate snapshot writes if the same fetch timestamp is retried.
        if all(c in old.columns for c in identity_cols):
            old_key = old[identity_cols].astype("string").fillna("")
            new_key = new[identity_cols].astype("string").fillna("")
            if (old_key.eq(new_key.iloc[0]).all(axis=1)).any():
                print(f"Existing identical snapshot found; not appending to {path.name}")
                return False
        combined = pd.concat([old, new], ignore_index=True, sort=False)
    else:
        combined = new
    combined.to_csv(path, index=False, na_rep="")
    return True


def run_forecast(event: dict) -> dict:
    now = pd.Timestamp(datetime.now(timezone.utc))
    valid_time = pd.Timestamp(event["race_start_utc"]).floor("h")
    lead_hours = (valid_time - now).total_seconds() / 3600

    if lead_hours <= 0:
        raise ValueError(
            "Race start is not in the future. Use observed mode after the event; "
            "do not label a post-start forecast as a pre-race snapshot."
        )
    if lead_hours > 16 * 24:
        raise ValueError(
            f"Race is {lead_hours:.1f} hours away, outside the typical 16-day "
            "forecast window. Retry closer to the event."
        )

    params = {
        "latitude": event["latitude"],
        "longitude": event["longitude"],
        "hourly": ",".join(VARIABLES.values()),
        "timezone": "UTC",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "start_date": valid_time.strftime("%Y-%m-%d"),
        "end_date": valid_time.strftime("%Y-%m-%d"),
    }
    payload = request_json(FORECAST_API + "?" + urlencode(params))
    row = {
        "season": int(event["season"]),
        "round": int(event["round"]),
        "race_name": str(event["race_name"]),
        "circuit_id": event["circuit_id"],
        "circuit_name": event["circuit_name"],
        "race_start_utc": pd.Timestamp(event["race_start_utc"]).isoformat(),
        "weather_valid_time_utc": valid_time.isoformat(),
        "fetched_at_utc": now.isoformat(),
        "forecast_lead_hours": round(lead_hours, 3),
        "latitude": event["latitude"],
        "longitude": event["longitude"],
        "weather_source": "Open-Meteo Forecast API",
        "weather_model": "Open-Meteo provider-selected forecast model",
        "weather_scope": "race_start_hour",
        "api_status": "ok",
        "api_error": "",
    }
    for output_col, api_col in VARIABLES.items():
        row[output_col] = get_hourly_value(payload, api_col, valid_time)

    if all(pd.isna(row.get(c)) for c in VARIABLES):
        row["api_status"] = "no_matching_hourly_data"
        row["api_error"] = "No hourly values matched race start time"

    append_immutable(
        FORECAST_PATH,
        row,
        ["season", "round", "circuit_id", "fetched_at_utc", "weather_valid_time_utc"],
    )
    return row


def run_observed_archive(event: dict) -> dict:
    valid_time = pd.Timestamp(event["race_start_utc"]).floor("h")
    today_utc = pd.Timestamp(datetime.now(timezone.utc)).date()
    if valid_time.date() >= today_utc:
        raise ValueError(
            "Event is not in the past UTC date yet. Run observed mode after the race "
            "and allow time for the historical archive to become available."
        )

    params = {
        "latitude": event["latitude"],
        "longitude": event["longitude"],
        "hourly": ",".join(VARIABLES.values()),
        "timezone": "UTC",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "start_date": valid_time.strftime("%Y-%m-%d"),
        "end_date": valid_time.strftime("%Y-%m-%d"),
    }
    payload = request_json(ARCHIVE_API + "?" + urlencode(params))
    fetched_at = pd.Timestamp(datetime.now(timezone.utc))
    row = {
        "season": int(event["season"]),
        "round": int(event["round"]),
        "race_name": str(event["race_name"]),
        "circuit_id": event["circuit_id"],
        "circuit_name": event["circuit_name"],
        "race_start_utc": pd.Timestamp(event["race_start_utc"]).isoformat(),
        "weather_valid_time_utc": valid_time.isoformat(),
        "fetched_at_utc": fetched_at.isoformat(),
        "latitude": event["latitude"],
        "longitude": event["longitude"],
        "weather_source": "Open-Meteo Historical Weather API",
        "weather_model": "archive_gridded_historical_estimate",
        "weather_scope": "race_start_hour",
        "data_semantics": "historical gridded estimate/reanalysis; not guaranteed station observation",
        "api_status": "ok",
        "api_error": "",
    }
    for output_col, api_col in VARIABLES.items():
        row[output_col] = get_hourly_value(payload, api_col, valid_time)

    if all(pd.isna(row.get(c)) for c in VARIABLES):
        row["api_status"] = "no_matching_hourly_data"
        row["api_error"] = "No hourly values matched race start time"

    append_immutable(
        OBSERVED_PATH,
        row,
        ["season", "round", "circuit_id", "fetched_at_utc", "weather_valid_time_utc"],
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["forecast", "observed"])
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", type=int, required=True)
    args = parser.parse_args()

    event = load_event(args.season, args.round)
    print(
        f"Event: {event['race_name']} | {args.season} R{args.round:02d} | "
        f"{event['circuit_name']} | valid={event['race_start_utc']}"
    )

    if args.mode == "forecast":
        row = run_forecast(event)
        output_path = FORECAST_PATH
    else:
        row = run_observed_archive(event)
        output_path = OBSERVED_PATH

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"weather_{args.mode}_{args.season}_{args.round:02d}_latest.json"
    report_path.write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")

    print("\nResult:")
    print(json.dumps(row, indent=2, default=str))
    print(f"\nCSV: {output_path}")
    print(f"Run report: {report_path}")
    print(
        "\nImportant: archive data is a historical gridded estimate, not a guaranteed "
        "direct weather-station observation. Missing values remain blank."
    )


if __name__ == "__main__":
    main()
