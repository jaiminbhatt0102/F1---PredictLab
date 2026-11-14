"""Generate experimental temperature-aware predictions from a near-race forecast.

Requires a forecast snapshot fetched approximately 18-30 hours before race start.
Writes to reports/ only and never replaces production prediction outputs.
"""
from __future__ import annotations
import argparse
from collections.abc import Mapping
from pathlib import Path
import sys
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.predict_upcoming_race import build_upcoming_rows, resolve_path

def find_col(frame: pd.DataFrame, choices: list[str], required: bool = True) -> str | None:
    for name in choices:
        if name in frame.columns:
            return name
    if required:
        raise ValueError(f"Expected one of columns {choices}; found {list(frame.columns)}")
    return None

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--round", dest="round_no", type=int, required=True)
    ap.add_argument("--processed-dir", default="data/processed")
    ap.add_argument("--history", default="data/features/race_training.csv")
    ap.add_argument("--model-dir", default="models/weather_candidates")
    ap.add_argument("--weather-csv", default="data/processed/weather_forecast_snapshots.csv")
    ap.add_argument("--output", default="reports/weather_candidate_predictions.csv")
    ap.add_argument("--min-lead-hours", type=float, default=18.0)
    ap.add_argument("--max-lead-hours", type=float, default=30.0)
    args = ap.parse_args()

    weather_path = resolve_path(args.weather_csv)
    if not weather_path.exists():
        raise FileNotFoundError(f"Weather snapshots not found: {weather_path}")
    weather = pd.read_csv(weather_path, low_memory=False)
    season_col = find_col(weather, ["season"])
    round_col = find_col(weather, ["round", "round_no"])
    circuit_col = find_col(weather, ["circuit_id"])
    temp_col = find_col(weather, ["temperature_c"])
    lead_col = find_col(weather, ["forecast_lead_hours", "lead_hours"])
    fetched_col = find_col(weather, ["fetched_at_utc", "fetched_at", "snapshot_fetched_at_utc"], required=False)
    status_col = find_col(weather, ["api_status", "status"], required=False)

    weather[season_col] = pd.to_numeric(weather[season_col], errors="coerce")
    weather[round_col] = pd.to_numeric(weather[round_col], errors="coerce")
    weather[lead_col] = pd.to_numeric(weather[lead_col], errors="coerce")
    weather[temp_col] = pd.to_numeric(weather[temp_col], errors="coerce")
    rows = weather[
        (weather[season_col] == args.season)
        & (weather[round_col] == args.round_no)
    ].copy()
    if status_col:
        rows = rows[rows[status_col].astype(str).str.lower().isin(["ok", "success", "200"])]
    rows = rows[rows[temp_col].notna() & rows[lead_col].between(args.min_lead_hours, args.max_lead_hours)]
    if rows.empty:
        all_rows = weather[
            (pd.to_numeric(weather[season_col], errors="coerce") == args.season)
            & (pd.to_numeric(weather[round_col], errors="coerce") == args.round_no)
        ]
        leads = pd.to_numeric(all_rows[lead_col], errors="coerce").dropna().tolist()
        raise ValueError(
            f"No usable temperature snapshot for {args.season} R{args.round_no} "
            f"with lead {args.min_lead_hours}-{args.max_lead_hours}h. "
            f"Stored lead hours for this event: {leads}. Fetch again closer to race start."
        )
    if fetched_col:
        rows[fetched_col] = pd.to_datetime(rows[fetched_col], errors="coerce", utc=True)
        rows = rows.sort_values(fetched_col)
    snapshot = rows.iloc[-1]
    temperature = float(snapshot[temp_col])
    circuit = str(snapshot[circuit_col]).strip()

    event = build_upcoming_rows(
        args.season, args.round_no, resolve_path(args.processed_dir),
        resolve_path(args.history)
    )
    if "circuit_id" not in event or not event["circuit_id"].astype(str).str.strip().eq(circuit).all():
        raise ValueError(
            f"Weather circuit_id={circuit!r} does not match the qualifying event circuit "
            f"{event.get('circuit_id', pd.Series(dtype=str)).astype(str).unique().tolist()}."
        )
    event["temperature_c"] = temperature
    output_cols = [
        "season", "round", "race_name", "race_date", "driver_id", "driver_code",
        "driver_given_name", "driver_family_name", "constructor_name", "grid",
        "qualifying_position", "temperature_c"
    ]
    out = event[[c for c in output_cols if c in event.columns]].copy()
    model_dir = resolve_path(args.model_dir)
    for target in ("target_win", "target_podium"):
        for kind in ("hist_gradient_boosting", "random_forest"):
            artifact_path = model_dir / f"{target}_temperature_{kind}.joblib"
            if not artifact_path.exists():
                raise FileNotFoundError(
                    f"Candidate missing: {artifact_path}. Run scripts/train_weather_candidates.py first."
                )
            artifact = joblib.load(artifact_path)
            if not isinstance(artifact, Mapping) or artifact.get("target") != target:
                raise ValueError(f"Invalid candidate artifact: {artifact_path}")
            features = artifact.get("features", [])
            missing = [c for c in features if c not in event.columns]
            if missing:
                raise ValueError(f"{artifact_path} requires missing columns: {missing}")
            prob = np.asarray(artifact["pipeline"].predict_proba(event[features]))[:, 1]
            if not np.isfinite(prob).all() or ((prob < 0) | (prob > 1)).any():
                raise ValueError(f"Invalid probability output from {artifact_path}")
            suffix = "hist_gradient_boosting" if kind == "hist_gradient_boosting" else "random_forest"
            out[f"{target}_{suffix}_probability"] = prob
            out[f"{target}_{suffix}_rank"] = out[f"{target}_{suffix}_probability"].rank(method="min", ascending=False).astype(int)
    out = out.sort_values("target_win_hist_gradient_boosting_probability", ascending=False)
    output = resolve_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False)
    print(f"Experimental weather predictions written to: {output}")
    print(f"Forecast temperature: {temperature:.1f} C; stored lead: {float(snapshot[lead_col]):.1f} hours")
    print(out.to_string(index=False))
    print("\nEXPERIMENTAL ONLY: compare with the production prediction output; do not treat as validated or replace production models.")

if __name__ == "__main__":
    main()
