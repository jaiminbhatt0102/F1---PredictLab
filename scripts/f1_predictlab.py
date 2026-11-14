"""
F1 PredictLab master controller.

Run from the repository root:
    python scripts/f1_predictlab.py

This controller reuses the project's existing scripts. It refreshes F1 data,
rebuilds normalized/features tables, refreshes historical weather experiments,
trains candidates in an isolated directory, and only promotes a new non-weather
model when its chronological validation score clearly beats the prior selected
model. Weather models remain experimental because their live forecast timing
contract must be validated over future events before production promotion.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

SCRIPTS = ROOT / "scripts"
REPORTS = ROOT / "reports"
MODELS = ROOT / "models"
DATASET = ROOT / "data" / "features" / "race_training.csv"


def say(message: str = "") -> None:
    print(message, flush=True)


def run_script(relative_script: str, *args: str, optional: bool = False) -> bool:
    """Run a project script with the same Python interpreter as this controller."""
    path = ROOT / relative_script
    if not path.exists():
        message = f"Missing script: {path}"
        if optional:
            say(f"[SKIP] {message}")
            return False
        raise FileNotFoundError(message)

    command = [PYTHON, str(path), *map(str, args)]
    say("\n" + "=" * 78)
    say("$ " + subprocess.list2cmdline(command))
    say("=" * 78)
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode:
        message = f"Command failed (exit {completed.returncode}): {relative_script}"
        if optional:
            say(f"[WARNING] {message}")
            return False
        raise RuntimeError(message)
    return True


def ask_int(prompt: str, default: int) -> int:
    value = input(f"{prompt} [{default}]: ").strip()
    return default if not value else int(value)


def ask_text(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return default if not value else value


def current_season() -> int:
    return datetime.now().year


def refresh_f1_data(full_history: bool = True) -> None:
    """Fetch fresh upstream data, normalize it, and rebuild the training table."""
    start = 2018 if full_history else current_season()
    end = current_season()
    run_script(
        "scripts/collect_f1_data.py",
        "--start", str(start), "--end", str(end), "--refresh",
    )
    run_script("scripts/normalize_f1_data.py")
    run_script("scripts/build_race_dataset.py")
    if not DATASET.exists():
        raise FileNotFoundError(f"Dataset was not created: {DATASET}")


def refresh_weather_history_and_experiment() -> None:
    """Refresh archived forecast training data and run the existing experiment."""
    run_script("scripts/build_weather_forecasts.py", optional=True)
    # This experiment is required for the temperature candidate table. If its
    # input/source isn't available, fail clearly rather than training stale data.
    run_script("scripts/run_weather_all_models_experiment.py")
    run_script("scripts/train_weather_candidates.py", optional=True)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def metric(report: dict[str, Any], target: str, kind: str, name: str) -> float | None:
    try:
        value = report["validation"]["model_summary"][target][kind][name]
        return float(value) if value is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def previous_selected_kinds(report: dict[str, Any] | None) -> dict[str, str]:
    if not report:
        return {}
    selected = report.get("selected_models", {})
    return {
        target: str(kind)
        for target, kind in selected.items()
        if target in ("target_win", "target_podium") and kind
    }


def safe_retrain_and_select() -> None:
    """
    Train into a temporary model directory first. Compare the best candidate to
    the previously selected model using chronological validation scores. Do not
    touch production artifacts unless the candidate improves Brier by >=1% and
    does not worsen log loss by >1%. Lower Brier/log loss are better.
    """
    if not DATASET.exists():
        raise FileNotFoundError(f"Missing {DATASET}. Run data refresh first.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    old_report_path = REPORTS / "model_evaluation.json"
    old_report = load_json(old_report_path)
    old_kinds = previous_selected_kinds(old_report)

    say("\nTraining all existing model families in an isolated temporary directory...")
    # Import after ROOT has been added to sys.path. This uses the existing trainer
    # but points all artifacts/report to temporary paths.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.models.train_baselines import train_and_evaluate

    with tempfile.TemporaryDirectory(prefix="f1_candidate_run_", dir=str(REPORTS)) as temp:
        temp_root = Path(temp)
        candidate_models = temp_root / "models"
        candidate_report_path = temp_root / "model_evaluation_candidate.json"
        candidate_report = train_and_evaluate(
            dataset_path=DATASET,
            model_dir=candidate_models,
            report_path=candidate_report_path,
        )
        # Preserve an auditable copy even when production is not promoted.
        audit_path = REPORTS / "model_evaluation_latest_candidate.json"
        audit_path.write_text(json.dumps(candidate_report, indent=2), encoding="utf-8")

        selected = candidate_report.get("selected_models", {})
        summary = candidate_report.get("validation", {}).get("model_summary", {})
        decisions: dict[str, Any] = {}
        any_promoted = False

        for target in ("target_win", "target_podium"):
            new_kind = selected.get(target)
            if not new_kind:
                decisions[target] = {"promoted": False, "reason": "No selected candidate"}
                continue

            old_kind = old_kinds.get(target)
            new_brier = metric(candidate_report, target, new_kind, "brier_score")
            new_loss = metric(candidate_report, target, new_kind, "log_loss")
            old_brier = metric(old_report, target, old_kind, "brier_score") if old_report and old_kind else None
            old_loss = metric(old_report, target, old_kind, "log_loss") if old_report and old_kind else None

            artifact_src = candidate_models / f"{target}_selected.joblib"
            artifact_dst = MODELS / f"{target}_selected.joblib"

            if not artifact_src.exists():
                decisions[target] = {"promoted": False, "reason": f"Missing staged artifact {artifact_src}"}
                continue

            if not artifact_dst.exists():
                # First installation only: no previous artifact to preserve.
                shutil.copy2(artifact_src, artifact_dst)
                any_promoted = True
                decisions[target] = {
                    "promoted": True, "reason": "No prior production artifact existed",
                    "new_model": new_kind, "new_brier": new_brier, "new_log_loss": new_loss,
                }
                continue

            # No previous report or comparable metrics means we cannot prove a gain.
            if old_kind is None or old_brier is None or old_loss is None:
                decisions[target] = {
                    "promoted": False,
                    "reason": "Kept current artifact: no comparable previous validation report",
                    "current_model": old_kind,
                    "candidate_model": new_kind,
                }
                continue

            # Require a clear improvement in both probability metrics. Compare
            # matching validation seasons; if they differ, do not auto-promote.
            old_seasons = (old_report or {}).get("validation", {}).get("validation_seasons")
            new_seasons = candidate_report.get("validation", {}).get("validation_seasons")
            comparable = old_seasons == new_seasons
            brier_gain = (old_brier - new_brier) / old_brier if old_brier > 0 else 0.0
            loss_not_materially_worse = new_loss <= old_loss * 1.01
            promote = (
                comparable and brier_gain >= 0.01 and loss_not_materially_worse
            )

            if promote:
                shutil.copy2(artifact_src, artifact_dst)
                any_promoted = True
                decisions[target] = {
                    "promoted": True, "reason": "Brier improved by at least 1% and log loss did not regress by more than 1%",
                    "previous_model": old_kind, "new_model": new_kind,
                    "previous_brier": old_brier, "new_brier": new_brier,
                    "previous_log_loss": old_loss, "new_log_loss": new_loss,
                    "brier_relative_gain": brier_gain,
                }
            else:
                reason = "Validation seasons differ" if not comparable else (
                    "Candidate did not meet the promotion threshold"
                )
                decisions[target] = {
                    "promoted": False, "reason": reason,
                    "kept_model": old_kind, "candidate_model": new_kind,
                    "previous_brier": old_brier, "candidate_brier": new_brier,
                    "previous_log_loss": old_loss, "candidate_log_loss": new_loss,
                    "brier_relative_gain": brier_gain,
                }

        # Record exactly what happened; do not replace the production evaluation
        # report if no model was promoted.
        decision_report = {
            "timestamp_local": datetime.now().astimezone().isoformat(),
            "dataset": str(DATASET.relative_to(ROOT)),
            "promotion_policy": {
                "metric": "Brier score",
                "minimum_relative_improvement": 0.01,
                "maximum_log_loss_regression": 0.01,
                "requires_same_validation_seasons": True,
            },
            "decisions": decisions,
            "any_model_promoted": any_promoted,
            "candidate_report": str(audit_path.relative_to(ROOT)),
            "production_report_updated": any_promoted,
        }
        decision_path = REPORTS / "model_promotion_decision.json"
        decision_path.write_text(json.dumps(decision_report, indent=2), encoding="utf-8")

        if any_promoted:
            # Keep the full candidate report, with per-target selected_models changed
            # to reflect the artifacts actually installed.
            installed_report = dict(candidate_report)
            actual_selected: dict[str, str] = {}
            for target in ("target_win", "target_podium"):
                decision = decisions.get(target, {})
                if decision.get("promoted"):
                    actual_selected[target] = str(decision.get("new_model", selected.get(target)))
                else:
                    actual_selected[target] = str(decision.get("kept_model", old_kinds.get(target, selected.get(target))))
            installed_report["selected_models"] = actual_selected
            installed_report["promotion_decisions"] = decisions
            old_report_path.write_text(json.dumps(installed_report, indent=2), encoding="utf-8")

    say("\nMODEL SELECTION RESULT")
    for target, decision in decisions.items():
        status = "PROMOTED" if decision.get("promoted") else "KEPT CURRENT"
        say(f"  {target}: {status} — {decision.get('reason')}")
        if decision.get("promoted"):
            say(f"    model={decision.get('new_model')}")
        else:
            say(f"    current={decision.get('kept_model', decision.get('current_model'))}; candidate={decision.get('candidate_model')}")
    say(f"\nAudit: {REPORTS / 'model_evaluation_latest_candidate.json'}")
    say(f"Decision: {REPORTS / 'model_promotion_decision.json'}")
    say("Weather candidates remain experimental; they are not silently promoted into production.")


def full_refresh_and_train(full_history: bool = True) -> None:
    refresh_f1_data(full_history=full_history)
    refresh_weather_history_and_experiment()
    safe_retrain_and_select()


def event_qualifying_prediction() -> None:
    season = ask_int("Season", current_season())
    round_no = ask_int("Round number", 18 if season == 2026 else 1)
    circuit = ask_text("Circuit ID (e.g. americas)", "americas" if season == 2026 and round_no == 18 else "")
    if not circuit:
        circuit = input("Circuit ID: ").strip()
    run_script(
        "scripts/predict_qualifying.py",
        "--season", str(season), "--round", str(round_no), "--circuit-id", circuit,
    )


def after_qualifying_race_prediction() -> None:
    season = ask_int("Season", current_season())
    round_no = ask_int("Round number", 18 if season == 2026 else 1)

    say("\nRefreshing the current season so published qualifying/grid data is available...")
    refresh_f1_data(full_history=False)
    # Fetch a timestamped race-start forecast. The weather candidate predictor will
    # accept it only at its trained 18-30h lead time; production prediction still runs.
    run_script(
        "scripts/fetch_event_weather.py", "forecast",
        "--season", str(season), "--round", str(round_no), optional=True,
    )
    run_script(
        "scripts/predict_upcoming_race.py",
        "--season", str(season), "--round", str(round_no),
        "--output", f"reports/race_prediction_{season}_{round_no:02d}.csv",
    )
    run_script(
        "scripts/predict_weather_candidates.py",
        "--season", str(season), "--round", str(round_no),
        "--output", f"reports/weather_candidate_prediction_{season}_{round_no:02d}.csv",
        optional=True,
    )
    say("\nProduction race predictions and experimental weather predictions are kept in separate files.")


def compare_weather_archives(season: int, round_no: int) -> None:
    forecast_path = ROOT / "data" / "processed" / "weather_forecast_snapshots.csv"
    observed_path = ROOT / "data" / "processed" / "weather_historical_archive.csv"
    if not forecast_path.exists() or not observed_path.exists():
        say("[WARNING] Forecast or historical archive file is missing; skipping comparison.")
        return
    import pandas as pd

    forecast = pd.read_csv(forecast_path, low_memory=False)
    observed = pd.read_csv(observed_path, low_memory=False)
    for frame in (forecast, observed):
        frame["season"] = pd.to_numeric(frame.get("season"), errors="coerce")
        frame["round"] = pd.to_numeric(frame.get("round"), errors="coerce")
    f = forecast[(forecast["season"] == season) & (forecast["round"] == round_no)].copy()
    o = observed[(observed["season"] == season) & (observed["round"] == round_no)].copy()
    if f.empty or o.empty:
        say("[WARNING] No matching forecast and archive rows for this event; skipping comparison.")
        return
    if "api_status" in f:
        f = f[f["api_status"].astype(str).str.lower().isin(["ok", "success", "200"])]
    if "api_status" in o:
        o = o[o["api_status"].astype(str).str.lower().isin(["ok", "success", "200"])]
    if f.empty or o.empty:
        say("[WARNING] No successful forecast/archive records for this event.")
        return
    if "fetched_at_utc" in f:
        f["fetched_at_utc"] = pd.to_datetime(f["fetched_at_utc"], errors="coerce", utc=True)
        f = f.sort_values("fetched_at_utc")
    if "fetched_at_utc" in o:
        o["fetched_at_utc"] = pd.to_datetime(o["fetched_at_utc"], errors="coerce", utc=True)
        o = o.sort_values("fetched_at_utc")
    fr, obs = f.iloc[-1], o.iloc[-1]
    variables = [
        "temperature_c", "relative_humidity_pct", "precipitation_mm",
        "cloud_cover_pct", "wind_speed_kmh", "wind_direction_deg",
    ]
    comparison: dict[str, Any] = {
        "season": season, "round": round_no,
        "forecast_source": fr.get("weather_source", fr.get("source")),
        "archive_source": obs.get("weather_source", obs.get("source")),
        "archive_interpretation": "Historical gridded estimate/reanalysis; not guaranteed circuit-station observation.",
        "forecast_fetched_at_utc": fr.get("fetched_at_utc"),
        "archive_fetched_at_utc": obs.get("fetched_at_utc"),
        "weather_valid_time_utc": fr.get("weather_valid_time_utc"),
        "variables": {},
    }
    for variable in variables:
        try:
            fv = float(fr[variable])
            ov = float(obs[variable])
            if not (pd.isna(fv) or pd.isna(ov)):
                comparison["variables"][variable] = {
                    "forecast": fv, "archive": ov, "absolute_error": abs(fv - ov),
                    "signed_error_archive_minus_forecast": ov - fv,
                }
                continue
        except (KeyError, TypeError, ValueError):
            pass
        comparison["variables"][variable] = {
            "forecast": fr.get(variable), "archive": obs.get(variable),
            "absolute_error": None, "signed_error_archive_minus_forecast": None,
        }
    REPORTS.mkdir(parents=True, exist_ok=True)
    output = REPORTS / f"weather_comparison_{season}_{round_no:02d}.json"
    output.write_text(json.dumps(comparison, indent=2, default=str), encoding="utf-8")
    say(f"Forecast/archive comparison saved: {output}")


def post_race_workflow() -> None:
    season = ask_int("Season", current_season())
    round_no = ask_int("Round number", 18 if season == 2026 else 1)
    say("\nRefreshing F1 results and retraining only if validation promotion criteria pass...")
    full_refresh_and_train(full_history=False)
    run_script(
        "scripts/fetch_event_weather.py", "observed",
        "--season", str(season), "--round", str(round_no), optional=True,
    )
    compare_weather_archives(season, round_no)


def show_status() -> None:
    say("\nF1 PREDICTLAB STATUS")
    for label, path in [
        ("Race training data", DATASET),
        ("Production win model", MODELS / "target_win_selected.joblib"),
        ("Production podium model", MODELS / "target_podium_selected.joblib"),
        ("Production evaluation report", REPORTS / "model_evaluation.json"),
        ("Weather historical data", ROOT / "data" / "processed" / "weather_forecasts_experimental.csv"),
        ("Live forecast snapshots", ROOT / "data" / "processed" / "weather_forecast_snapshots.csv"),
        ("Weather candidate training report", REPORTS / "weather_candidate_training.json"),
        ("Last promotion decision", REPORTS / "model_promotion_decision.json"),
    ]:
        say(f"  [{'OK' if path.exists() else 'MISSING'}] {label}: {path.relative_to(ROOT)}")
    if DATASET.exists():
        import pandas as pd
        df = pd.read_csv(DATASET, usecols=lambda c: c in {"season", "round"})
        if "season" in df and not df.empty:
            say(f"  Rows: {len(df):,}; seasons: {int(df.season.min())}-{int(df.season.max())}")


def run_all() -> None:
    """Convenience workflow: refresh/train, then predict qualifying for an event."""
    full_refresh_and_train(full_history=True)
    say("\nData/model refresh is complete. Next, create the pre-qualifying forecast.")
    event_qualifying_prediction()
    say("\nAfter qualifying is officially published, run this controller again and choose option 3.")


def menu() -> None:
    while True:
        say("\n" + "=" * 68)
        say("F1 PREDICTLAB — MASTER PIPELINE")
        say("=" * 68)
        say("1. Full refresh: fetch F1 data + weather history, evaluate, safely retrain/select")
        say("2. Predict qualifying (pre-session)")
        say("3. After qualifying: refresh current season + predict race + experimental weather")
        say("4. Post-race: refresh results + safe retraining + archive weather comparison")
        say("5. Status")
        say("6. Exit")
        choice = input("\nChoose an option [1-6]: ").strip()
        try:
            if choice == "1":
                full_refresh_and_train(full_history=True)
            elif choice == "2":
                event_qualifying_prediction()
            elif choice == "3":
                after_qualifying_race_prediction()
            elif choice == "4":
                post_race_workflow()
            elif choice == "5":
                show_status()
            elif choice == "6":
                say("Exiting.")
                return
            else:
                say("Choose a number from 1 to 6.")
        except KeyboardInterrupt:
            say("\nCancelled by user.")
        except Exception as exc:
            say(f"\n[ERROR] {exc}")
            say("Pipeline stopped at the failed step. Fix the reported issue and rerun the controller.")
        input("\nPress Enter to return to the menu...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-all", action="store_true",
        help="Refresh/train safely, then prompt for a pre-qualifying prediction.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show the presence of core data/model/report files and exit.",
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.status:
        show_status()
    elif args.run_all:
        try:
            run_all()
        except Exception as exc:
            say(f"\n[ERROR] {exc}")
            raise
    else:
        menu()


if __name__ == "__main__":
    main()
