"""Read-only service layer for the F1 PredictLab API.

Everything returned here is read from files the existing pipeline already wrote
(schedule, normalized sessions, evaluation reports, weather snapshots and
prediction CSVs). Nothing is generated, estimated or mocked. Model artifacts are
only listed, never loaded. Local file paths are never returned to callers.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# F1_PROJECT_ROOT lets tests and demos point the app at a copy of the data.
ROOT = Path(os.getenv("F1_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
PROCESSED = "data/processed"
SESSIONS = ("qualifying", "sprint", "race")

# The experimental weather contract documented in scripts/predict_weather_candidates.py
WEATHER_MIN_LEAD_HOURS = 18.0
WEATHER_MAX_LEAD_HOURS = 30.0
# A race this many hours past its scheduled start with no result row is flagged stale.
RESULT_GRACE_HOURS = 8.0


class ServiceError(Exception):
    """Safe, user-presentable failure. `message` never contains paths or tracebacks."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------- file helpers
def _p(rel: str) -> Path:
    return ROOT / rel


def _mtime_iso(rel: str) -> str | None:
    path = _p(rel)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any) -> Any:
    """Convert pandas/numpy scalars to JSON-safe values; NaN becomes None (never 0)."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except Exception:  # noqa: BLE001
            return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _read_csv(rel: str) -> pd.DataFrame | None:
    path = _p(rel)
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("data_unreadable", "A data file could not be read. Re-run the data pipeline.", 503) from exc


def _read_json(rel: str) -> dict | None:
    path = _p(rel)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("report_unreadable", "An evaluation report is damaged and cannot be shown.", 503) from exc
    return data if isinstance(data, dict) else None


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    cols = [c for c in columns if c in frame.columns]
    return [{c: _clean(row[c]) for c in cols} for _, row in frame[cols].iterrows()]


# ------------------------------------------------------------------- schedule
def _schedule() -> pd.DataFrame:
    frame = _read_csv(f"{PROCESSED}/f1_session_schedule.csv")
    if frame is None or frame.empty:
        raise ServiceError("schedule_unavailable", "The race schedule has not been collected yet.", 503)
    return frame


def _calendar(season: int) -> dict[int, dict]:
    data = _read_json(f"data/raw/{season}_calendar.json") or {}
    out: dict[int, dict] = {}
    for ev in data.get("events", []):
        try:
            out[int(ev["round"])] = ev
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _session_frame(season: int, session: str) -> pd.DataFrame | None:
    return _read_csv(f"{PROCESSED}/{season}_{session}_normalized.csv")


def _rounds_with_session(season: int, session: str) -> set[int]:
    frame = _session_frame(season, session)
    if frame is None or "round" not in frame.columns:
        return set()
    return {int(r) for r in frame["round"].dropna().unique()}


def _is_sprint_weekend(event_format: str | None) -> bool:
    return bool(event_format) and event_format != "conventional"


def _event_dict(row: pd.Series, cal: dict[int, dict], done: dict[str, set[int]]) -> dict:
    rnd = int(row["round"])
    fmt = _clean(row.get("event_format"))
    sprint_weekend = _is_sprint_weekend(fmt)
    q, s, r = (rnd in done["qualifying"], rnd in done["sprint"], rnd in done["race"])
    if r:
        stage = "race_complete"
    elif q and (s or not sprint_weekend):
        stage = "qualifying_complete"
    elif q:
        stage = "qualifying_complete_sprint_pending"
    else:
        stage = "upcoming"
    ev = cal.get(rnd, {})
    session_times = {k: _utc_iso(ev.get(k)) for k in ("first_practice_utc", "sprint_qualifying_utc", "sprint_utc", "qualifying_utc") if ev.get(k)}

    def state(have: bool, applicable: bool = True) -> str:
        if not applicable:
            return "not_applicable"
        return "complete" if have else "pending"

    return {
        "season": int(row["season"]),
        "round": rnd,
        "race_name": _clean(row.get("race_name")),
        "country": _clean(row.get("country")),
        "locality": _clean(row.get("locality")),
        "circuit_id": ev.get("circuit_id"),
        "circuit_name": ev.get("circuit_name"),
        "event_date": _clean(row.get("event_date")),
        "race_start_utc": _utc_iso(row.get("race_start_utc")),
        "event_format": fmt,
        "is_sprint_weekend": sprint_weekend,
        "weekend_stage": stage,
        "session_times_utc": session_times,
        "sessions": {
            "qualifying": state(q),
            "sprint": state(s, sprint_weekend),
            "race": state(r),
        },
    }


def _utc_iso(value: Any) -> str | None:
    value = _clean(value)
    if value is None or value == "":
        return None
    try:
        ts = pd.Timestamp(value)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        return ts.isoformat()
    except Exception:  # noqa: BLE001
        return None


def _validate_season(season: int) -> None:
    if season < 1950 or season > 2100:
        raise ServiceError("invalid_season", "Season must be between 1950 and 2100.", 422)


def list_events(season: int) -> dict:
    _validate_season(season)
    schedule = _schedule()
    rows = schedule[schedule["season"] == season].sort_values("round")
    if rows.empty:
        raise ServiceError("season_not_found", f"No schedule is available for {season}.", 404)
    cal = _calendar(season)
    done = {s: _rounds_with_session(season, s) for s in SESSIONS}
    events = [_event_dict(row, cal, done) for _, row in rows.iterrows()]
    now = _now()
    default_round = None
    for ev in events:
        start = ev["race_start_utc"]
        if ev["weekend_stage"] != "race_complete" and (start is None or pd.Timestamp(start) > pd.Timestamp(now) - pd.Timedelta(hours=RESULT_GRACE_HOURS)):
            default_round = ev["round"]
            break
    if default_round is None:
        completed = [e["round"] for e in events if e["weekend_stage"] == "race_complete"]
        default_round = completed[-1] if completed else None
    return {
        "season": season,
        "generated_at_utc": now.isoformat(),
        "schedule_updated_at_utc": _mtime_iso(f"{PROCESSED}/f1_session_schedule.csv"),
        "default_round": default_round,
        "events": events,
    }


def get_event(season: int, round_no: int) -> dict:
    data = list_events(season)
    for ev in data["events"]:
        if ev["round"] == round_no:
            return ev
    raise ServiceError("event_not_found", f"Round {round_no} is not on the {season} schedule.", 404)


def available_seasons() -> list[int]:
    return sorted(int(s) for s in _schedule()["season"].unique())


# ------------------------------------------------------------------- sessions
_SESSION_COLUMNS = {
    "qualifying": ["position", "driver_code", "driver_given_name", "driver_family_name", "constructor_name", "q1", "q2", "q3"],
    "sprint": ["position", "driver_code", "driver_given_name", "driver_family_name", "constructor_name", "grid", "points", "status", "time", "fastest_lap_time"],
    "race": ["position", "driver_code", "driver_given_name", "driver_family_name", "constructor_name", "grid", "points", "status", "time", "fastest_lap_time"],
}


def get_sessions(season: int, round_no: int) -> dict:
    event = get_event(season, round_no)
    out: dict[str, Any] = {}
    for session in SESSIONS:
        frame = _session_frame(season, session)
        rel = f"{PROCESSED}/{season}_{session}_normalized.csv"
        if event["sessions"][session] == "not_applicable":
            out[session] = {"status": "not_applicable", "rows": [], "source_updated_at_utc": None}
            continue
        rows: list[dict] = []
        if frame is not None and "round" in frame.columns:
            part = frame[frame["round"] == round_no].copy()
            if "position" in part.columns:
                part = part.sort_values("position")
            rows = _records(part, _SESSION_COLUMNS[session])
        out[session] = {
            "status": "complete" if rows else "pending",
            "rows": rows,
            "source_updated_at_utc": _mtime_iso(rel) if rows else None,
        }
    return {"event": event, "generated_at_utc": _now().isoformat(), "sessions": out}


# ---------------------------------------------------------------------- weather
_WEATHER_VALUES = ["temperature_c", "relative_humidity_pct", "precipitation_mm", "cloud_cover_pct", "wind_speed_kmh", "wind_direction_deg"]


def _weather_row(row: pd.Series, kind: str, semantics: str) -> dict:
    out = {"kind": kind, "semantics": semantics}
    for col in ["circuit_id", "fetched_at_utc", "weather_valid_time_utc", "race_start_utc", "forecast_lead_hours", "weather_source", "weather_model", "weather_scope", "api_status", *_WEATHER_VALUES]:
        out[col] = _clean(row[col]) if col in row.index else None
    for col in ("fetched_at_utc", "weather_valid_time_utc", "race_start_utc"):
        out[col] = _utc_iso(out[col])
    return out


def get_weather(season: int, round_no: int) -> dict:
    event = get_event(season, round_no)
    snapshots: list[dict] = []
    frame = _read_csv(f"{PROCESSED}/weather_forecast_snapshots.csv")
    if frame is not None and {"season", "round"} <= set(frame.columns):
        part = frame[(frame["season"] == season) & (frame["round"] == round_no)]
        if "fetched_at_utc" in part.columns:
            part = part.sort_values("fetched_at_utc", ascending=False)
        snapshots = [_weather_row(r, "forecast_snapshot", "Forecast captured at fetched_at_utc. Never rewritten later.") for _, r in part.iterrows()]
    archive: list[dict] = []
    hist = _read_csv(f"{PROCESSED}/weather_historical_archive.csv")
    if hist is not None and {"season", "round"} <= set(hist.columns):
        part = hist[(hist["season"] == season) & (hist["round"] == round_no)]
        archive = [_weather_row(r, "historical_archive", "Gridded historical estimate or reanalysis, not a station observation.") for _, r in part.iterrows()]
    prev = _read_csv(f"{PROCESSED}/weather_forecasts_experimental.csv")
    previous_runs: list[dict] = []
    if prev is not None and {"season", "round"} <= set(prev.columns):
        part = prev[(prev["season"] == season) & (prev["round"] == round_no)]
        previous_runs = [_weather_row(r, "previous_run_forecast", "Forecast value recorded about 24 hours before the race, used for model experiments.") for _, r in part.iterrows()]
    for snap in snapshots:
        lead = snap.get("forecast_lead_hours")
        snap["lead_time_check"] = _lead_check(lead)
    return {
        "event": event,
        "generated_at_utc": _now().isoformat(),
        "contract": {"min_lead_hours": WEATHER_MIN_LEAD_HOURS, "max_lead_hours": WEATHER_MAX_LEAD_HOURS},
        "forecast_snapshots": snapshots,
        "historical_archive": archive,
        "previous_run_forecasts": previous_runs,
    }


def _lead_check(lead: float | None) -> dict:
    if lead is None:
        return {"status": "unknown", "message": "Forecast lead time is not recorded."}
    if lead > WEATHER_MAX_LEAD_HOURS:
        return {"status": "too_early", "message": f"This forecast was captured about {round(lead)} hours before the race. The weather model needs one captured {WEATHER_MIN_LEAD_HOURS:g} to {WEATHER_MAX_LEAD_HOURS:g} hours before."}
    if lead < WEATHER_MIN_LEAD_HOURS:
        return {"status": "too_late", "message": f"This forecast was captured only {round(lead)} hours before the race, which is outside the {WEATHER_MIN_LEAD_HOURS:g} to {WEATHER_MAX_LEAD_HOURS:g} hour window."}
    return {"status": "ok", "message": "Forecast lead time matches the weather model contract."}


# ------------------------------------------------------------------------ models
def _artifact_kind(stem: str) -> tuple[str, str]:
    """`target_win_extra_trees` -> ('target_win', 'extra_trees')."""
    for target in ("target_win", "target_podium"):
        if stem.startswith(target + "_"):
            return target, stem[len(target) + 1 :]
    return stem, ""


def get_models() -> dict:
    evaluation = _read_json("reports/model_evaluation.json") or {}
    selected = evaluation.get("selected_models", {})
    quali_report = _find_qualifying_report()
    models: list[dict] = []

    def add(rel: str, target: str, kind: str | None, status: str, label: str) -> None:
        path = _p(rel)
        models.append({
            "id": path.stem,
            "target": target,
            "model_kind": kind,
            "status": status,
            "status_label": label,
            "artifact_available": path.exists(),
            "artifact_updated_at_utc": _mtime_iso(rel),
        })

    for target in ("target_win", "target_podium"):
        add(f"models/{target}_selected.joblib", target, selected.get(target), "production", "Production")
    add("models/qualifying_position_selected.joblib", "qualifying_position", (quali_report or {}).get("selected_model"), "production", "Production")
    sprint_report = _read_json("reports/sprint_model_evaluation.json") or {}
    add("models/sprint_position_selected.joblib", "sprint_position", sprint_report.get("selected_model"), "production", "Production")
    cand_dir = _p("models/candidates")
    if cand_dir.exists():
        for f in sorted(cand_dir.glob("*.joblib")):
            target, kind = _artifact_kind(f.stem)
            add(f"models/candidates/{f.name}", target, kind or None, "candidate", "Candidate")
    wx_dir = _p("models/weather_candidates")
    if wx_dir.exists():
        for f in sorted(wx_dir.glob("*.joblib")):
            target, kind = _artifact_kind(f.stem)
            add(f"models/weather_candidates/{f.name}", target, kind or None, "experimental", "Experimental weather-assisted")
    prod_ready = all(m["artifact_available"] for m in models if m["status"] == "production") and any(m["status"] == "production" for m in models)
    return {
        "generated_at_utc": _now().isoformat(),
        "status": "ready" if prod_ready else "not_ready",
        "promotion_note": "Models are never promoted by the web app. Promotion happens only through the backend training workflow.",
        "models": models,
    }


def _find_qualifying_report() -> dict | None:
    reports = sorted(_p("reports").glob("round_*_qualifying_report.json")) if _p("reports").exists() else []
    if not reports:
        return None
    return _read_json(f"reports/{reports[-1].name}")


# ------------------------------------------------------------------- evaluations
_METRIC_KEYS = ("rows", "positive_count", "positive_rate", "brier_score", "log_loss", "roc_auc")


def _metrics(block: Any) -> dict | None:
    if not isinstance(block, dict):
        return None
    out = {k: _clean(block.get(k)) for k in _METRIC_KEYS}
    return out if any(v is not None for v in out.values()) else None


def get_evaluations() -> dict:
    prod = _read_json("reports/model_evaluation.json")
    production = None
    if prod:
        validation = prod.get("validation", {})
        holdout = prod.get("final_holdout", {})
        selected = prod.get("selected_models", {})
        targets = []
        for target in ("target_win", "target_podium"):
            rolling = validation.get("model_summary", {}).get(target, {})
            hold = holdout.get("model_summary", {}).get(target, {})
            kinds = list(dict.fromkeys([*rolling.keys(), *hold.keys()]))
            targets.append({
                "target": target,
                "selected_model": selected.get(target),
                "models": [{
                    "model_kind": k,
                    "is_selected": k == selected.get(target),
                    "is_baseline": k == "prior_baseline",
                    "rolling_validation": _metrics(rolling.get(k)),
                    "holdout": _metrics(hold.get(k)),
                    "by_season": [
                        {"season": int(season), **(_metrics(m) or {})}
                        for season, m in sorted((rolling.get(k, {}).get("by_season") or {}).items())
                    ],
                } for k in kinds],
            })
        production = {
            "evaluated_at_utc": _mtime_iso("reports/model_evaluation.json"),
            "dataset_rows": prod.get("dataset_rows"),
            "dataset_seasons": prod.get("seasons"),
            "features_used": prod.get("features_used"),
            "features_excluded_for_leakage": prod.get("features_excluded_for_leakage"),
            "validation_seasons": validation.get("validation_seasons"),
            "selection_rule": validation.get("selection_metric"),
            "holdout_season": holdout.get("season"),
            "holdout_training_seasons": holdout.get("training_seasons"),
            "production_fit_seasons": prod.get("production_fit_seasons"),
            "notes": [n for n in (prod.get("note"), holdout.get("note")) if n],
            "targets": targets,
        }

    quali = None
    qr = _find_qualifying_report()
    if qr:
        rolling = qr.get("rolling_validation", {})
        quali = {
            "evaluated_at_utc": None,
            "event": qr.get("event"),
            "selected_model": qr.get("selected_model"),
            "training_rows": qr.get("training_rows"),
            "holdout": {"season": qr.get("chronological_holdout", {}).get("season"), **(qr.get("chronological_holdout", {}).get("metrics") or {})},
            "rolling_validation": [
                {"model_kind": k, "mean_mae_positions": _clean(v.get("mean_mae_positions")), "folds": v.get("folds", [])}
                for k, v in rolling.items()
            ],
            "caveats": qr.get("caveats", []),
        }

    weather = None
    wx = _read_json("reports/weather_all_models_experiment.json")
    wt = _read_json("reports/weather_candidate_training.json")
    wc = _read_json("reports/weather_collection_report.json")
    if wx or wt:
        weather = {
            "status": "experimental",
            "evaluated_at_utc": _mtime_iso("reports/weather_all_models_experiment.json"),
            "production_artifacts_modified": (wx or {}).get("production_artifacts_modified"),
            "weather_source": (wx or {}).get("weather_source"),
            "lead_time_definition": (wc or {}).get("lead_time_definition"),
            "timing_contract": (wt or {}).get("timing_contract"),
            "selection_note": (wt or {}).get("selection_note"),
            "validation_notes": (wx or {}).get("validation_notes", []),
            "coverage_by_season": [
                {"season": int(s), "race_count": v.get("race_count"), "non_null_races": v.get("non_null_races")}
                for s, v in sorted(((wx or {}).get("weather_coverage_by_season") or {}).items())
            ],
            "temperature_folds": _weather_folds((wx or {}).get("temperature_experiment", {})),
            "six_variable": _weather_six((wx or {}).get("six_variable_experiment", {})),
            "candidates": _safe_candidates((wt or {}).get("candidates")),
        }
    return {"generated_at_utc": _now().isoformat(), "production": production, "qualifying": quali, "weather_experimental": weather}


def _safe_candidates(block: dict | None) -> list[dict]:
    """Candidate training summary without artifact file paths."""
    out = []
    for target, kinds in (block or {}).items():
        for kind, info in (kinds or {}).items():
            out.append({"target": target, "model_kind": kind, "rows": info.get("rows"), "trained_through_season": info.get("trained_through_season")})
    return out


def _weather_models(models: dict) -> list[dict]:
    return [{"model_kind": k, "baseline": _metrics(v.get("baseline")), "weather_enhanced": _metrics(v.get("weather_enhanced"))} for k, v in (models or {}).items()]


def _weather_folds(block: dict) -> dict:
    return {
        "weather_features": block.get("weather_features"),
        "training_evaluation_seasons": block.get("training_evaluation_seasons"),
        "folds": [
            {
                "test_season": fold.get("test_season"),
                "targets": [
                    {"target": t, "train_seasons": d.get("train_seasons"), "train_rows": d.get("train_rows"), "test_rows": d.get("test_rows"), "models": _weather_models(d.get("models", {}))}
                    for t, d in (fold.get("targets") or {}).items()
                ],
            }
            for _, fold in sorted((block.get("folds") or {}).items())
        ],
    }


def _weather_six(block: dict) -> dict:
    return {
        "weather_features": block.get("weather_features"),
        "caveat": block.get("caveat"),
        "targets": [
            {"target": t, "train_seasons": d.get("train_seasons"), "test_seasons": d.get("test_seasons"), "train_rows": d.get("train_rows"), "test_rows": d.get("test_rows"), "models": _weather_models(d.get("models", {}))}
            for t, d in (block.get("evaluation") or {}).items()
        ],
    }


# ------------------------------------------------------------------ predictions
def _driver_lookup() -> dict[str, dict]:
    """driver_id -> display names, taken from the most recent normalized race file."""
    for season in sorted(available_seasons(), reverse=True):
        frame = _session_frame(season, "race")
        if frame is None or frame.empty:
            continue
        latest = frame[frame["round"] == frame["round"].max()]
        return {
            str(r["driver_id"]): {
                "driver_code": _clean(r.get("driver_code")),
                "driver_name": f"{r.get('driver_given_name', '')} {r.get('driver_family_name', '')}".strip(),
                "constructor_id": _clean(r.get("constructor_id")),
                "constructor_name": _clean(r.get("constructor_name")),
            }
            for _, r in latest.iterrows()
        }
    return {}


def _input_availability(event: dict, weather: dict) -> list[dict]:
    s = event["sessions"]
    wx_state = "missing"
    wx_note = "No forecast has been captured for this event."
    snaps = weather["forecast_snapshots"]
    if snaps:
        check = snaps[0]["lead_time_check"]
        wx_state = "available" if check["status"] == "ok" else check["status"]
        wx_note = check["message"]
    return [
        {"key": "qualifying", "label": "Qualifying results", "state": "available" if s["qualifying"] == "complete" else "not_yet_available"},
        {"key": "sprint", "label": "Sprint results", "state": {"complete": "available", "pending": "not_yet_available", "not_applicable": "not_applicable"}[s["sprint"]]},
        {"key": "race", "label": "Race results", "state": "completed" if s["race"] == "complete" else "not_yet_available"},
        {"key": "weather", "label": "Weather forecast", "state": wx_state, "detail": wx_note},
    ]


# ----------------------------------------------------------------------- analysis
def season_summary(season: int) -> dict:
    """Driver results for a season, computed only from actual normalized race rows."""
    _validate_season(season)
    frame = _session_frame(season, "race")
    if frame is None or frame.empty:
        raise ServiceError("season_data_unavailable", f"No race results have been collected for {season}.", 404)
    frame = frame.copy()
    frame["position"] = pd.to_numeric(frame["position"], errors="coerce")
    frame["grid"] = pd.to_numeric(frame["grid"], errors="coerce")
    frame["points"] = pd.to_numeric(frame["points"], errors="coerce").fillna(0)
    out = []
    for driver_id, g in frame.groupby("driver_id"):
        latest = g.sort_values("round").iloc[-1]
        finished = g["position"].dropna()
        started = g[g["grid"] > 0]["grid"]
        out.append({
            "driver_id": driver_id,
            "driver_code": _clean(latest.get("driver_code")),
            "driver_name": f"{latest.get('driver_given_name', '')} {latest.get('driver_family_name', '')}".strip(),
            "constructor_name": _clean(latest.get("constructor_name")),
            "races": int(len(g)),
            "points": float(g["points"].sum()),
            "wins": int((g["position"] == 1).sum()),
            "podiums": int((g["position"] <= 3).sum()),
            "average_finish": _clean(round(float(finished.mean()), 2)) if len(finished) else None,
            "average_grid": _clean(round(float(started.mean()), 2)) if len(started) else None,
        })
    out.sort(key=lambda d: (-d["points"], -d["wins"], d["driver_name"]))
    return {
        "season": season,
        "generated_at_utc": _now().isoformat(),
        "source_updated_at_utc": _mtime_iso(f"{PROCESSED}/{season}_race_normalized.csv"),
        "rounds_covered": int(frame["round"].nunique()),
        "drivers": out,
    }


# -------------------------------------------------------------------------- status
def get_status(version: str) -> dict:
    now = _now()
    seasons: list[int] = []
    schedule_ok = True
    try:
        seasons = available_seasons()
    except ServiceError:
        schedule_ok = False

    latest_completed = None
    stale_events: list[dict] = []
    coverage: list[dict] = []
    if schedule_ok:
        sched = _schedule()
        for season in seasons:
            done = {s: _rounds_with_session(season, s) for s in SESSIONS}
            coverage.append({"season": season, "races_scheduled": int((sched["season"] == season).sum()), "races_with_results": len(done["race"]), "qualifying_sessions": len(done["qualifying"]), "sprint_sessions": len(done["sprint"])})
        latest_season = seasons[-1]
        done_races = _rounds_with_session(latest_season, "race")
        completed_rows = sched[(sched["season"] == latest_season) & (sched["round"].isin(done_races))]
        if not completed_rows.empty:
            last = completed_rows.sort_values("round").iloc[-1]
            latest_completed = {"season": latest_season, "round": int(last["round"]), "race_name": _clean(last["race_name"])}
        due = sched[(sched["season"] == latest_season) & (~sched["round"].isin(done_races))]
        for _, r in due.iterrows():
            start = _utc_iso(r["race_start_utc"])
            if start and pd.Timestamp(start) < pd.Timestamp(now) - pd.Timedelta(hours=RESULT_GRACE_HOURS):
                stale_events.append({"season": latest_season, "round": int(r["round"]), "race_name": _clean(r["race_name"])})

    dataset = _read_csv("data/features/race_training.csv")
    data_ready = schedule_ok and dataset is not None and not dataset.empty
    latest_season_for_report = seasons[-1] if seasons else None
    data = {
        "status": "not_ready" if not data_ready else ("stale" if stale_events else "ready"),
        "seasons": seasons,
        "coverage": coverage,
        "latest_completed_event": latest_completed,
        "training_rows": int(len(dataset)) if dataset is not None else None,
        "training_table_updated_at_utc": _mtime_iso("data/features/race_training.csv"),
        "last_collection_at_utc": _mtime_iso(f"data/raw/{latest_season_for_report}_collection_report.json") if latest_season_for_report else None,
        "schedule_updated_at_utc": _mtime_iso(f"{PROCESSED}/f1_session_schedule.csv"),
        "stale_events": stale_events,
    }

    models = get_models()
    prod = [m for m in models["models"] if m["status"] == "production"]
    models_summary = {
        "status": models["status"],
        "production": prod,
        "candidate_count": sum(m["status"] == "candidate" for m in models["models"]),
        "experimental_count": sum(m["status"] == "experimental" for m in models["models"]),
    }

    weather_latest = None
    snaps = _read_csv(f"{PROCESSED}/weather_forecast_snapshots.csv")
    if snaps is not None and not snaps.empty and "fetched_at_utc" in snaps.columns:
        row = snaps.sort_values("fetched_at_utc").iloc[-1]
        w = _weather_row(row, "forecast_snapshot", "")
        w.update({"season": int(row["season"]), "round": int(row["round"]), "race_name": _clean(row.get("race_name")), "lead_time_check": _lead_check(w.get("forecast_lead_hours"))})
        w.pop("semantics", None)
        weather_latest = w
    weather = {"status": "ready" if weather_latest and weather_latest.get("api_status") == "ok" else "not_ready", "latest_snapshot": weather_latest}

    overall = "ready" if data["status"] == "ready" and models["status"] == "ready" else ("partial" if data_ready or models["status"] == "ready" else "not_ready")
    if data["status"] == "stale" and overall == "ready":
        overall = "partial"
    return {
        "status": overall,
        "service": {"name": "F1 PredictLab API", "version": version},
        "generated_at_utc": now.isoformat(),
        "data": data,
        "models": models_summary,
        "weather": weather,
        "capabilities": {
            "events": schedule_ok,
            "sessions": schedule_ok,
            "predictions_qualifying": (_p("models/qualifying_position_selected.joblib")).exists(),
            "predictions_sprint": (_p("models/sprint_position_selected.joblib")).exists(),
            "predictions_race": (_p("models/target_win_selected.joblib")).exists() and (_p("models/target_podium_selected.joblib")).exists(),
            "predictions_weather_experimental": (_p("models/weather_candidates")).exists(),
            "season_analysis": schedule_ok,
            "prediction_history": True,
            "pipeline_jobs": True,
            "live_predictions": False,
        },
    }


def data_version() -> dict:
    """Small, safe description of the data a prediction was made from."""
    latest = None
    try:
        seasons = available_seasons()
        for season in reversed(seasons):
            done = sorted(_rounds_with_session(season, "race"))
            if done:
                ev = get_event(season, done[-1])
                latest = {"season": season, "round": done[-1], "race_name": ev["race_name"]}
                break
    except ServiceError:
        pass
    dataset = _read_csv("data/features/race_training.csv")
    return {
        "dataset_updated_at_utc": _mtime_iso("data/features/race_training.csv"),
        "training_rows": int(len(dataset)) if dataset is not None else None,
        "latest_completed_event": latest,
    }


def constructor_summary(season: int) -> dict:
    _validate_season(season)
    frame = _session_frame(season, "race")
    if frame is None or frame.empty:
        raise ServiceError("season_data_unavailable", f"No race results have been collected for {season}.", 404)
    frame = frame.copy()
    frame["position"] = pd.to_numeric(frame["position"], errors="coerce")
    frame["points"] = pd.to_numeric(frame["points"], errors="coerce").fillna(0)
    out = []
    for name, g in frame.groupby("constructor_name"):
        out.append({
            "constructor_name": name,
            "points": float(g["points"].sum()),
            "wins": int((g["position"] == 1).sum()),
            "podiums": int((g["position"] <= 3).sum()),
            "best_finish": _clean(g["position"].min()),
        })
    out.sort(key=lambda d: (-d["points"], -d["wins"], d["constructor_name"]))
    return {"season": season, "generated_at_utc": _now().isoformat(), "constructors": out}


def circuit_history(circuit_id: str) -> dict:
    """Race winners and podiums at one circuit across every collected season."""
    if not circuit_id or len(circuit_id) > 60 or not all(c.isalnum() or c in "_-" for c in circuit_id):
        raise ServiceError("invalid_circuit", "That circuit ID is not valid.", 422)
    rows: list[dict] = []
    name = None
    for season in available_seasons():
        frame = _session_frame(season, "race")
        if frame is None or "circuit_id" not in frame.columns:
            continue
        part = frame[frame["circuit_id"] == circuit_id].copy()
        if part.empty:
            continue
        part["position"] = pd.to_numeric(part["position"], errors="coerce")
        part["grid"] = pd.to_numeric(part["grid"], errors="coerce")
        name = name or _clean(part.iloc[0].get("circuit_name"))
        for rnd, g in part.groupby("round"):
            g = g.sort_values("position")
            top = g.iloc[0] if not g.empty else None
            if top is None or pd.isna(top["position"]) or top["position"] != 1:
                continue
            pole = g[g["grid"] == 1]
            rows.append({
                "season": season, "round": int(rnd), "race_name": _clean(top.get("race_name")),
                "winner": f"{top.get('driver_given_name', '')} {top.get('driver_family_name', '')}".strip(),
                "winner_team": _clean(top.get("constructor_name")),
                "winner_grid": _clean(top.get("grid")),
                "podium": [f"{r.get('driver_family_name', '')}" for _, r in g.head(3).iterrows()],
                "pole_sitter_won": bool(not pole.empty and pole.iloc[0]["position"] == 1),
            })
    if not rows:
        raise ServiceError("circuit_not_found", "No collected races were found at that circuit.", 404)
    rows.sort(key=lambda r: -r["season"])
    return {"circuit_id": circuit_id, "circuit_name": name, "generated_at_utc": _now().isoformat(), "races": rows}


# ------------------------------------------------------------ driver and team pages
def _slug(name: str | None) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _race_and_quali(season: int) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    race = _session_frame(season, "race")
    if race is None or race.empty:
        raise ServiceError("season_data_unavailable", f"No race results have been collected for {season}.", 404)
    race = race.copy()
    for col in ("position", "grid", "points"):
        race[col] = pd.to_numeric(race[col], errors="coerce")
    return race, _session_frame(season, "qualifying"), _session_frame(season, "sprint")


def _lookup(frame: pd.DataFrame | None, rnd: int, key_col: str, key: str, value_col: str):
    if frame is None or key_col not in frame.columns:
        return None
    hit = frame[(frame["round"] == rnd) & (frame[key_col] == key)]
    if hit.empty:
        return None
    return _clean(pd.to_numeric(hit.iloc[0][value_col], errors="coerce"))


def driver_profile(season: int, code: str) -> dict:
    _validate_season(season)
    code = (code or "").upper()
    if not code.isalnum() or len(code) > 5:
        raise ServiceError("invalid_driver", "That is not a valid driver code.", 422)
    race, quali, sprint = _race_and_quali(season)
    mine = race[race["driver_code"] == code].sort_values("round")
    if mine.empty:
        raise ServiceError("driver_not_found", f"{code} has no collected races in {season}.", 404)
    latest = mine.iloc[-1]
    summary = season_summary(season)["drivers"]
    standing = next((i + 1 for i, d in enumerate(summary) if d["driver_code"] == code), None)
    me = next((d for d in summary if d["driver_code"] == code), {})
    results = []
    for _, r in mine.iterrows():
        rnd = int(r["round"])
        results.append({
            "round": rnd, "race_name": _clean(r["race_name"]), "circuit_id": _clean(r.get("circuit_id")),
            "constructor_name": _clean(r.get("constructor_name")),
            "grid": _clean(r["grid"]), "position": _clean(r["position"]), "points": _clean(r["points"]), "status": _clean(r.get("status")),
            "qualifying_position": _lookup(quali, rnd, "driver_code", code, "position"),
            "sprint_position": _lookup(sprint, rnd, "driver_code", code, "position"),
            "sprint_points": _lookup(sprint, rnd, "driver_code", code, "points"),
        })
    seasons = [s for s in available_seasons() if (f := _session_frame(s, "race")) is not None and (f["driver_code"] == code).any()]
    return {
        "season": season, "generated_at_utc": _now().isoformat(), "source_updated_at_utc": _mtime_iso(f"{PROCESSED}/{season}_race_normalized.csv"),
        "driver": {"code": code, "driver_id": _clean(latest["driver_id"]), "name": f"{latest['driver_given_name']} {latest['driver_family_name']}".strip(),
                   "constructor_name": _clean(latest["constructor_name"]), "team_slug": _slug(latest["constructor_name"])},
        "standing": {"rank": standing, "points": me.get("points"), "wins": me.get("wins"), "podiums": me.get("podiums"), "races": me.get("races"),
                     "average_finish": me.get("average_finish"), "average_grid": me.get("average_grid"), "drivers_ranked": len(summary)},
        "seasons_with_data": seasons,
        "results": results,
    }


def team_profile(season: int, slug: str) -> dict:
    _validate_season(season)
    race, _, _ = _race_and_quali(season)
    names = {_slug(n): n for n in race["constructor_name"].dropna().unique()}
    if slug not in names:
        raise ServiceError("team_not_found", "That team has no collected races in this season.", 404)
    name = names[slug]
    mine = race[race["constructor_name"] == name]
    table = constructor_summary(season)["constructors"]
    standing = next((i + 1 for i, c in enumerate(table) if c["constructor_name"] == name), None)
    me = next((c for c in table if c["constructor_name"] == name), {})
    drivers = season_summary(season)["drivers"]
    lineup = [d for d in drivers if d["constructor_name"] == name]
    # A driver who changed teams appears under both; list everyone who scored or raced for this team.
    for code in mine["driver_code"].unique():
        if not any(d["driver_code"] == code for d in lineup):
            row = next((d for d in drivers if d["driver_code"] == code), None)
            if row:
                lineup.append(row)
    rounds = []
    for rnd, g in mine.groupby("round"):
        g = g.sort_values("position")
        rounds.append({
            "round": int(rnd), "race_name": _clean(g.iloc[0]["race_name"]), "points": float(g["points"].fillna(0).sum()),
            "best_finish": _clean(g["position"].min()),
            "drivers": [{"driver_code": _clean(r["driver_code"]), "position": _clean(r["position"]), "grid": _clean(r["grid"]), "points": _clean(r["points"])} for _, r in g.iterrows()],
        })
    return {
        "season": season, "generated_at_utc": _now().isoformat(), "source_updated_at_utc": _mtime_iso(f"{PROCESSED}/{season}_race_normalized.csv"),
        "team": {"name": name, "slug": slug},
        "standing": {"rank": standing, "points": me.get("points"), "wins": me.get("wins"), "podiums": me.get("podiums"), "best_finish": me.get("best_finish"), "teams_ranked": len(table)},
        "drivers": [{"driver_code": d["driver_code"], "name": d["driver_name"], "points": d["points"], "wins": d["wins"], "podiums": d["podiums"], "races": d["races"]} for d in lineup],
        "rounds": sorted(rounds, key=lambda r: r["round"]),
    }
