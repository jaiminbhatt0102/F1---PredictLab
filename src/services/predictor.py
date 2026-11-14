"""Live prediction service.

Runs inference with the trained model artifacts (never training), enforces what
information may be used at each stage, and saves every result as an immutable snapshot.

Stages
------
before qualifying  -> past races only            (qualifying order)
before the sprint  -> past races only            (sprint order)
after qualifying   -> this weekend's qualifying (and sprint) results   (race)
before the race    -> official starting grid when published, else the qualifying order (race)
"""
from __future__ import annotations
import logging
import warnings
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.models.probabilities import normalize_podium, normalize_win
from src.services import data_service as ds
from src.services import snapshots

STAGES: dict[tuple[str, str], dict[str, str]] = {
    ("qualifying", "pre_qualifying"): {
        "label": "Before qualifying",
        "uses": "Results of earlier races only. Nothing from this weekend.",
    },
    ("sprint", "pre_sprint"): {
        "label": "Before the sprint",
        "uses": "Results of earlier races only. Nothing from this weekend.",
    },
    ("race", "post_qualifying"): {
        "label": "After qualifying",
        "uses": "This weekend’s qualifying (and sprint) results plus earlier races.",
    },
    ("race", "pre_race"): {
        "label": "Before the race",
        "uses": "The starting grid plus this weekend’s qualifying (and sprint) results and earlier races.",
    },
}

WEATHER_KIND = "hist_gradient_boosting"

log = logging.getLogger("f1_predictlab.predictor")
RETRAIN_HINT = "Open Updates and choose “Retrain the prediction models”. It takes a few minutes and only needs doing once."

def _p(rel: str):
    return ds.ROOT / rel


def _not_ready(request: dict, event: dict | None, code: str, message: str, next_step: str | None = None, inputs: list | None = None) -> dict:
    return {
        "status": "not_ready",
        "code": code,
        "message": message,
        "next_step": next_step,
        "requested": request,
        "event": event,
        "stage": _stage_info(request),
        "input_availability": inputs or [],
        "rows": [],
        "warnings": [],
    }


def _stage_info(request: dict) -> dict | None:
    info = STAGES.get((request["session"], request["checkpoint"]))
    return None if info is None else {"checkpoint": request["checkpoint"], **info}


# ------------------------------------------------------------------ stage checks
def check_stage(event: dict, session: str, checkpoint: str) -> tuple[str, str, str | None] | None:
    """Return (code, message, next_step) when this prediction must not be made, else None."""
    if (session, checkpoint) not in STAGES:
        return ("stage_not_supported", "That combination isn’t available. Qualifying is predicted before qualifying, the sprint before the sprint, and the race after qualifying or before the race.", None)
    s = event["sessions"]
    taken = {"qualifying": "qualifying", "sprint": "the sprint", "race": "the race"}[session]
    if s[session] == "complete":
        return ("already_happened", f"{taken.capitalize()} has already taken place, so a new prediction would not be a fair test. Open Prediction history to see what we predicted at the time.", None)
    if session == "sprint" and s["sprint"] == "not_applicable":
        return ("no_sprint", "This Grand Prix has no sprint.", None)
    if session == "race":
        if s["qualifying"] != "complete":
            return ("qualifying_required", "We need the qualifying results before we can make this race prediction.", "Check back once qualifying has finished and the data has updated.")
        if event["is_sprint_weekend"] and s["sprint"] != "complete":
            return ("sprint_required", "This is a sprint weekend. We need the sprint result before we can make this race prediction.", "Check back once the sprint has finished and the data has updated.")
    # Earlier races must be in the data, otherwise the form figures would be out of date.
    if event["round"] > 1:
        try:
            prev = ds.get_event(event["season"], event["round"] - 1)
        except ds.ServiceError:
            prev = None
        if prev and prev["sessions"]["race"] != "complete":
            return ("earlier_race_missing", f"The previous race (round {prev['round']}, {prev['race_name']}) has no collected result yet, so recent form would be out of date.", "Update the race data first.")
    return None


# ----------------------------------------------------------------------- helpers
def _grid_official(season: int, round_no: int) -> dict[str, int] | None:
    path = _p(f"data/processed/{season}_starting_grid.csv")
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path)
        frame = frame[(frame["season"] == season) & (frame["round"] == round_no)]
        if frame.empty:
            return None
        return {str(r["driver_id"]): int(r["grid"]) for _, r in frame.iterrows()}
    except Exception:  # noqa: BLE001
        return None


def _load(rel: str, expected_target: str) -> Mapping:
    path = _p(rel)
    if not path.exists():
        raise ds.ServiceError("model_missing", "The prediction model hasn’t been trained yet. Use “Train models” on the Updates page.", 503)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            art = joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        log.exception("Could not open model file %s", path.name)
        raise ds.ServiceError("model_unreadable", f"The saved prediction model was made with different software versions and can’t be opened on this computer. {RETRAIN_HINT}", 503) from exc
    if not isinstance(art, Mapping) or art.get("target") != expected_target or art.get("pipeline") is None:
        raise ds.ServiceError("model_invalid", "A prediction model file is not in the expected format. Retrain the models.", 503)
    return art


def _weather_context(season: int, round_no: int) -> dict:
    try:
        data = ds.get_weather(season, round_no)
    except ds.ServiceError:
        return {"available": False}
    snaps = data["forecast_snapshots"]
    if not snaps:
        return {"available": False}
    s = snaps[0]
    return {
        "available": True,
        "captured_at_utc": s["fetched_at_utc"],
        "valid_time_utc": s["weather_valid_time_utc"],
        "lead_hours": s["forecast_lead_hours"],
        "temperature_c": s["temperature_c"],
        "rain_mm": s["precipitation_mm"],
        "wind_kmh": s["wind_speed_kmh"],
        "humidity_pct": s["relative_humidity_pct"],
        "lead_time_check": s["lead_time_check"],
        "circuit_id": s.get("circuit_id"),
    }


def _names() -> dict[str, dict]:
    return ds._driver_lookup()


def _roster(frame: pd.DataFrame) -> pd.DataFrame:
    latest = frame.sort_values(["season", "round"]).iloc[-1]
    return frame[(frame["season"] == int(latest["season"])) & (frame["round"] == int(latest["round"]))][["driver_id", "constructor_id"]].drop_duplicates("driver_id")


def _order_rows(roster_pred: pd.DataFrame, names: dict[str, dict]) -> list[dict]:
    out = []
    for i, (_, r) in enumerate(roster_pred.sort_values(["pred", "driver_id"]).iterrows(), start=1):
        info = names.get(str(r["driver_id"]), {})
        out.append({
            "predicted_order": i,
            "driver_id": r["driver_id"],
            "driver_code": info.get("driver_code"),
            "driver_name": info.get("driver_name") or str(r["driver_id"]),
            "constructor_name": info.get("constructor_name") or str(r["constructor_id"]),
            "predicted_position": float(r["pred"]),
        })
    return out


# ------------------------------------------------------------------- inference
def _predict_order(session: str, event: dict) -> tuple[list[dict], dict]:
    """Qualifying or sprint order from past form only."""
    from scripts import predict_qualifying as pq
    from src.models import train_sprint as ts

    if session == "qualifying":
        art = _load("models/qualifying_position_selected.joblib", "qualifying_position")
        prepare = pq.prepare_features
    else:
        art = _load("models/sprint_position_selected.joblib", "sprint_position")
        prepare = ts.prepare
    through = art.get("trained_through_event") or {}
    if (through.get("season"), through.get("round")) >= (event["season"], event["round"]):
        raise ds.ServiceError("model_saw_event", "The model was trained on this event already, so predicting it would not be fair. Retrain is not needed; this should not happen for an upcoming event.", 409)
    try:
        frame = pq.load_dataset(_p("data/features/race_training.csv"))
    except Exception as exc:  # noqa: BLE001
        raise ds.ServiceError("training_data_unavailable", "The training table is missing. Update the race data first.", 503) from exc
    roster = _roster(frame)
    rows = []
    for r in roster.itertuples(index=False):
        item = {"season": event["season"], "round": event["round"], "driver_id": str(r.driver_id), "constructor_id": str(r.constructor_id), "circuit_id": event["circuit_id"] or "unknown"}
        item.update(pq.history_features(frame, str(r.driver_id)))
        rows.append(item)
    future = pd.DataFrame(rows)
    try:
        future["pred"] = art["pipeline"].predict(prepare(future))
    except Exception as exc:  # noqa: BLE001
        raise ds.ServiceError("prediction_failed", "The model could not produce a prediction from the current data.", 500) from exc
    if not np.isfinite(future["pred"]).all():
        raise ds.ServiceError("prediction_failed", "The model produced an invalid number, so nothing was saved.", 500)
    meta = {"model_kind": art.get("model_kind"), "trained_through_event": through or None}
    return _order_rows(future, _names()), meta


def _race_event_rows(event: dict) -> tuple[pd.DataFrame, str, list[str]]:
    from scripts.predict_upcoming_race import build_upcoming_rows

    try:
        rows = build_upcoming_rows(event["season"], event["round"], _p("data/processed"), _p("data/features/race_training.csv"))
    except (FileNotFoundError, ValueError) as exc:
        raise ds.ServiceError("inputs_not_ready", "This weekend’s qualifying data isn’t ready to use yet. Update the race data and try again.", 503) from exc
    warnings_out: list[str] = []
    official = _grid_official(event["season"], event["round"])
    source = "qualifying_order"
    if official:
        grid = rows["driver_id"].astype(str).map(official)
        if grid.notna().all():
            rows["grid"] = grid.astype(float)
            source = "official_grid"
        else:
            warnings_out.append("A starting grid file exists but doesn’t cover every driver, so the qualifying order was used instead.")
    return rows, source, warnings_out


def _race_probabilities(rows: pd.DataFrame) -> dict[str, np.ndarray]:
    from scripts.predict_upcoming_race import load_prediction_artifact

    out = {}
    for target in ("target_win", "target_podium"):
        try:
            pipeline, features, kind = load_prediction_artifact(_p(f"models/{target}_selected.joblib"), target)
        except FileNotFoundError as exc:
            raise ds.ServiceError("model_missing", "The prediction model hasn’t been trained yet. Use “Train models” on the Updates page.", 503) from exc
        except Exception as exc:  # noqa: BLE001
            log.exception("Could not open model file for %s", target)
            raise ds.ServiceError("model_unreadable", f"The saved prediction model was made with different software versions and can’t be opened on this computer. {RETRAIN_HINT}", 503) from exc
        missing = [c for c in features if c not in rows.columns]
        if missing:
            raise ds.ServiceError("model_mismatch", "The model expects information this weekend’s data doesn’t have. Retrain the models.", 503)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prob = np.asarray(pipeline.predict_proba(rows[features]))[:, 1]
        if not np.isfinite(prob).all() or ((prob < 0) | (prob > 1)).any():
            raise ds.ServiceError("prediction_failed", "The model produced an invalid probability, so nothing was saved.", 500)
        out[target] = normalize_win(prob) if target == "target_win" else normalize_podium(prob)
        out[f"{target}_kind"] = kind
    return out


def _weather_probabilities(rows: pd.DataFrame, weather: dict, event: dict) -> tuple[dict[str, np.ndarray], dict]:
    if not weather.get("available"):
        raise ds.ServiceError("weather_missing", "No weather forecast has been captured for this Grand Prix yet.", 409)
    if weather["lead_time_check"]["status"] != "ok":
        raise ds.ServiceError("weather_lead_time", weather["lead_time_check"]["message"], 409)
    if weather.get("temperature_c") is None:
        raise ds.ServiceError("weather_missing", "The latest forecast has no temperature value.", 409)
    if weather.get("circuit_id") and event.get("circuit_id") and weather["circuit_id"] != event["circuit_id"]:
        raise ds.ServiceError("weather_circuit_mismatch", "The stored forecast is for a different circuit.", 409)
    data = rows.copy()
    data["temperature_c"] = float(weather["temperature_c"])
    out: dict[str, Any] = {}
    for target in ("target_win", "target_podium"):
        art = _load(f"models/weather_candidates/{target}_temperature_{WEATHER_KIND}.joblib", target)
        features = list(art.get("features", []))
        missing = [c for c in features if c not in data.columns]
        if missing:
            raise ds.ServiceError("model_mismatch", "The weather model expects information this weekend’s data doesn’t have.", 503)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prob = np.asarray(art["pipeline"].predict_proba(data[features]))[:, 1]
        if not np.isfinite(prob).all() or ((prob < 0) | (prob > 1)).any():
            raise ds.ServiceError("prediction_failed", "The weather model produced an invalid probability.", 500)
        out[target] = normalize_win(prob) if target == "target_win" else normalize_podium(prob)
    return out, {"model_kind": WEATHER_KIND, "weather_feature": "air temperature"}


def _race_rows_out(rows: pd.DataFrame, probs: dict[str, np.ndarray]) -> list[dict]:
    frame = rows.copy()
    frame["p_win"] = probs["target_win"]
    frame["p_pod"] = probs["target_podium"]
    frame["win_rank"] = frame["p_win"].rank(method="first", ascending=False).astype(int)
    frame["pod_rank"] = frame["p_pod"].rank(method="first", ascending=False).astype(int)
    frame = frame.sort_values("win_rank")
    out = []
    for _, r in frame.iterrows():
        def num(col: str, row=r):
            v = row.get(col)
            return None if v is None or pd.isna(v) else float(v)
        out.append({
            "driver_id": r["driver_id"],
            "driver_code": r.get("driver_code"),
            "driver_name": f"{r.get('driver_given_name', '')} {r.get('driver_family_name', '')}".strip(),
            "constructor_name": r.get("constructor_name"),
            "grid": num("grid"),
            "qualifying_position": num("qualifying_position"),
            "sprint_position": num("sprint_position"),
            "win_probability": float(r["p_win"]),
            "win_rank": int(r["win_rank"]),
            "podium_probability": float(r["p_pod"]),
            "podium_rank": int(r["pod_rank"]),
        })
    return out


# --------------------------------------------------------------------- generate
def generate(season: int, round_no: int, session: str, checkpoint: str, use_weather: bool = False, trigger: str = "manual") -> dict:
    """Create, save and return a prediction. Returns a not_ready result instead of guessing."""
    request = {"season": season, "round": round_no, "session": session, "checkpoint": checkpoint, "use_weather": use_weather}
    event = ds.get_event(season, round_no)
    weather = _weather_context(season, round_no)
    inputs = ds._input_availability(event, {"forecast_snapshots": [{"lead_time_check": weather["lead_time_check"]}] if weather.get("available") else []})

    problem = check_stage(event, session, checkpoint)
    if problem:
        return _not_ready(request, event, problem[0], problem[1], problem[2], inputs)
    if use_weather and session != "race":
        return _not_ready(request, event, "weather_race_only", "The weather-assisted view is available for the race only.", None, inputs)

    warnings_out: list[str] = []
    model_info: dict[str, Any]
    extra: dict[str, Any] = {}
    try:
        if session in ("qualifying", "sprint"):
            rows, meta = _predict_order(session, event)
            output_type = "predicted_qualifying_position" if session == "qualifying" else "predicted_sprint_position"
            output_label = "Predicted qualifying order" if session == "qualifying" else "Predicted sprint order"
            model_info = {"status": "production", **meta}
            warnings_out += [
                "The driver list is copied from the latest completed race. Check it against the confirmed entry list.",
                "This estimate uses past results only. It does not know about practice pace, weather or penalties.",
            ]
            if session == "sprint":
                warnings_out.append("Sprint predictions are rough. On past seasons the order was typically about 4 places off per driver.")
        else:
            race_rows, grid_source, grid_warn = _race_event_rows(event)
            warnings_out += grid_warn
            extra["grid_source"] = grid_source
            if checkpoint == "pre_race" and grid_source == "qualifying_order":
                warnings_out.append("The official starting grid isn’t available yet, so the qualifying order is used as the grid. Penalties are not included.")
            if checkpoint == "post_qualifying":
                warnings_out.append("The grid is the qualifying order. Penalties are not included.")
            if use_weather:
                probs, meta = _weather_probabilities(race_rows, weather, event)
                model_info = {"status": "experimental", **meta}
                warnings_out.append("Experimental. This version also uses the race-day temperature forecast. It is not the main prediction.")
            else:
                probs = _race_probabilities(race_rows)
                model_info = {"status": "production", "win_model_kind": probs["target_win_kind"], "podium_model_kind": probs["target_podium_kind"]}
            rows = _race_rows_out(race_rows, probs)
            output_type = "win_and_podium_probability"
            output_label = "Chance of winning and of finishing on the podium"
            warnings_out.append("These are probabilities, not certainties. Incidents, strategy and reliability can change the result.")
    except ds.ServiceError as exc:
        return _not_ready(request, event, exc.code, exc.message, None, inputs)

    experimental = bool(use_weather)
    created = datetime.now(timezone.utc).isoformat()
    snap = {
        "snapshot_id": snapshots.new_id(season, round_no, session, checkpoint, experimental),
        "schema_version": 1,
        "status": "ready",
        "kind": "experimental" if experimental else "production",
        "created_at_utc": created,
        "generated_at_utc": created,
        "trigger": trigger,
        "requested": request,
        "event_name": event["race_name"],
        "event": event,
        "stage": _stage_info(request),
        "output_type": output_type,
        "output_label": output_label,
        "model": model_info,
        "inputs": {**extra, "weather": weather, "data_version": ds.data_version()},
        "input_availability": inputs,
        "warnings": warnings_out,
        "rows": rows,
    }
    snapshots.save(snap)
    return {**snap, "saved": True, "code": None, "message": None}
