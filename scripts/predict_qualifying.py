"""Train a leakage-aware qualifying-position model and forecast a future event.

Default use:
    python scripts/predict_qualifying.py --season 2026 --round 18 --circuit-id americas

The prediction roster is copied from the latest completed event in race_training.csv.
Review that roster before relying on the forecast. The output is qualifying order,
not an official starting grid (which can change because of penalties).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.extra_features import TEAM_PACE_FEATURES, team_pace_for_event  # noqa: E402

NUMERIC_FEATURES = [
    "season",
    "round",
    "driver_prior_mean_qualifying_3",
    "driver_prior_mean_finish_3",
    "driver_prior_mean_points_3",
    "driver_prior_race_count",
]
CATEGORICAL_FEATURES = ["driver_id", "constructor_id", "circuit_id"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "qualifying_position"


def make_pipeline(kind: str, numeric_features: list[str] | None = None) -> Pipeline:
    numeric_features = NUMERIC_FEATURES if numeric_features is None else numeric_features
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    prep = ColumnTransformer([
        ("numeric", numeric, numeric_features),
        ("categorical", categorical, CATEGORICAL_FEATURES),
    ], remainder="drop")

    if kind == "extra_trees":
        estimator = ExtraTreesRegressor(
            n_estimators=500, min_samples_leaf=3, n_jobs=-1, random_state=42
        )
    elif kind == "random_forest":
        estimator = RandomForestRegressor(
            n_estimators=400, min_samples_leaf=3, n_jobs=-1, random_state=42
        )
    elif kind == "gradient_boosting":
        estimator = GradientBoostingRegressor(
            n_estimators=200, learning_rate=0.05, max_depth=2,
            min_samples_leaf=5, loss="huber", random_state=42
        )
    else:
        raise ValueError(f"Unknown model: {kind}")

    return Pipeline([("preprocess", prep), ("model", estimator)])


def load_dataset(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "season", "round", "driver_id", "constructor_id", "circuit_id",
        TARGET, "race_position_num", "race_points_num",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Training table missing required columns: {missing}")

    frame["season"] = pd.to_numeric(frame["season"], errors="coerce")
    frame["round"] = pd.to_numeric(frame["round"], errors="coerce")
    for col in [TARGET, "race_position_num", "race_points_num"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    if "race_date_sort" in frame:
        frame["_date_sort"] = pd.to_datetime(frame["race_date_sort"], errors="coerce")
        sort_cols = ["_date_sort", "season", "round", "driver_id"]
    else:
        sort_cols = ["season", "round", "driver_id"]
    frame = frame.dropna(subset=["season", "round", "driver_id"]).copy()
    frame["season"] = frame["season"].astype(int)
    frame["round"] = frame["round"].astype(int)
    frame = frame.sort_values(sort_cols, na_position="last").reset_index(drop=True)

    # Shift before rolling: a driver's current qualifying result is never one of
    # the features used to predict that same qualifying result.
    frame["driver_prior_mean_qualifying_3"] = (
        frame.groupby("driver_id", sort=False)[TARGET]
        .transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    )
    return frame


def prepare_features(frame: pd.DataFrame, numeric_features: list[str] | None = None) -> pd.DataFrame:
    numeric_features = NUMERIC_FEATURES if numeric_features is None else numeric_features
    out = frame[numeric_features + CATEGORICAL_FEATURES].copy()
    for col in CATEGORICAL_FEATURES:
        out[col] = out[col].fillna("unknown").astype(str)
    for col in numeric_features:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.replace([np.inf, -np.inf], np.nan)


def add_team_pace_columns(future: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Team-pace columns for upcoming rows, computed exactly as in the training table."""
    pace = team_pace_for_event(history, future[["constructor_id", "season", "round"]])
    return future.drop(columns=[c for c in TEAM_PACE_FEATURES if c in future.columns]).merge(pace, on="constructor_id", how="left")


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        "rows": int(len(y_true)),
        "mae_positions": float(mean_absolute_error(y_true, y_pred)),
        "rmse_positions": float(np.sqrt(mean_squared_error(y_true, y_pred))),
    }


def choose_numeric_features(labeled: pd.DataFrame, validation_seasons: list[int], model_kinds: list[str]) -> tuple[list[str], dict]:
    """Original inputs, or plus team pace: whichever has the lower validation error. Ties keep the simpler set."""
    options = {"original inputs": list(NUMERIC_FEATURES)}
    if all(c in labeled.columns and labeled[c].notna().mean() > 0.5 for c in TEAM_PACE_FEATURES):
        options["plus team pace"] = NUMERIC_FEATURES + TEAM_PACE_FEATURES
    scores = {}
    for name, numeric in options.items():
        per_kind = []
        for kind in model_kinds:
            maes = []
            for season in validation_seasons:
                train, valid = labeled[labeled["season"] < season], labeled[labeled["season"] == season]
                if train.empty or valid.empty:
                    continue
                model = make_pipeline(kind, numeric)
                model.fit(prepare_features(train, numeric), train[TARGET].to_numpy(dtype=float))
                maes.append(metrics(valid[TARGET].to_numpy(float), model.predict(prepare_features(valid, numeric)))["mae_positions"])
            per_kind.append(float(np.mean(maes)))
        scores[name] = min(per_kind)
    best = min(scores, key=lambda n: (round(scores[n], 4), len(options[n])))
    return options[best], {"chosen": best, "best_model_validation_mae_by_option": scores, "features": options[best]}


def history_features(history: pd.DataFrame, driver_id: str) -> dict:
    h = history[history["driver_id"].astype(str) == str(driver_id)].sort_values(
        ["season", "round"]
    )
    # Use only completed events in the training table. The last row is the
    # driver's latest known event, so these aggregates include that event.
    q = pd.to_numeric(h[TARGET], errors="coerce").dropna().tail(3)
    finish = pd.to_numeric(h["race_position_num"], errors="coerce").dropna().tail(3)
    points = pd.to_numeric(h["race_points_num"], errors="coerce").dropna().tail(3)
    return {
        "driver_prior_mean_qualifying_3": float(q.mean()) if len(q) else np.nan,
        "driver_prior_mean_finish_3": float(finish.mean()) if len(finish) else np.nan,
        "driver_prior_mean_points_3": float(points.mean()) if len(points) else np.nan,
        "driver_prior_race_count": int(len(h)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/features/race_training.csv")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--round", type=int, default=18)
    parser.add_argument("--circuit-id", default="americas")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    model_dir = Path(args.model_dir)
    report_dir = Path(args.report_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    frame = load_dataset(dataset_path)
    labeled = frame.dropna(subset=[TARGET]).copy()
    if labeled.empty:
        raise ValueError("No qualifying-position labels found in the training table.")

    # Select models only on seasons before the fixed 2025 holdout.
    seasons = sorted(int(s) for s in labeled["season"].unique())
    holdout_season = 2025 if 2025 in seasons else seasons[-1]
    pre_holdout = [s for s in seasons if s < holdout_season]
    if len(pre_holdout) < 3:
        raise ValueError(f"Need at least three pre-holdout seasons; found {pre_holdout}")
    validation_seasons = pre_holdout[-3:]
    model_kinds = ["extra_trees", "random_forest", "gradient_boosting"]
    numeric_used, feature_choice = choose_numeric_features(labeled, validation_seasons, model_kinds)
    X_all = prepare_features(labeled, numeric_used)
    y_all = labeled[TARGET].to_numpy(dtype=float)

    validation: dict[str, dict] = {}
    for kind in model_kinds:
        folds = []
        for val_season in validation_seasons:
            train_mask = labeled["season"] < val_season
            valid_mask = labeled["season"] == val_season
            train = labeled.loc[train_mask]
            valid = labeled.loc[valid_mask].dropna(subset=[TARGET])
            if train.empty or valid.empty:
                continue
            model = make_pipeline(kind, numeric_used)
            model.fit(prepare_features(train, numeric_used), train[TARGET].to_numpy(dtype=float))
            pred = model.predict(prepare_features(valid, numeric_used))
            fold = {"season": int(val_season), **metrics(valid[TARGET].to_numpy(float), pred)}
            folds.append(fold)
        if not folds:
            raise ValueError(f"No rolling validation folds for {kind}")
        validation[kind] = {
            "mean_mae_positions": float(np.mean([f["mae_positions"] for f in folds])),
            "folds": folds,
        }

    selected_kind = min(
        model_kinds,
        key=lambda k: (validation[k]["mean_mae_positions"], k),
    )

    # Keep 2025 as an untouched chronological holdout for the selected model.
    holdout = labeled[labeled["season"] == holdout_season]
    holdout_train = labeled[labeled["season"] < holdout_season]
    if not holdout.empty and not holdout_train.empty:
        holdout_model = make_pipeline(selected_kind, numeric_used)
        holdout_model.fit(
            prepare_features(holdout_train, numeric_used),
            holdout_train[TARGET].to_numpy(dtype=float),
        )
        holdout_pred = holdout_model.predict(prepare_features(holdout, numeric_used))
        holdout_metrics = metrics(holdout[TARGET].to_numpy(float), holdout_pred)
    else:
        holdout_metrics = {"note": "Holdout metrics unavailable for this dataset."}

    # Fit production model after evaluation, including completed 2026 Round 17.
    production = make_pipeline(selected_kind, numeric_used)
    production.fit(X_all, y_all)
    artifact = {
        "pipeline": production,
        "features": numeric_used + CATEGORICAL_FEATURES,
        "numeric_features": numeric_used,
        "target": TARGET,
        "model_kind": selected_kind,
        "trained_through_season": int(labeled["season"].max()),
        "trained_through_event": {
            "season": int(labeled.sort_values(["season", "round"]).iloc[-1]["season"]),
            "round": int(labeled.sort_values(["season", "round"]).iloc[-1]["round"]),
        },
        "prediction_checkpoint": "pre_qualifying",
        "note": "Forecast qualifying order; not official starting grid.",
    }
    model_path = model_dir / "qualifying_position_selected.joblib"
    joblib.dump(artifact, model_path)

    # Use the latest completed event as a provisional entry list. This makes the
    # lineup assumption explicit; replace the roster if confirmed entries differ.
    latest_event = frame.sort_values(["season", "round"]).iloc[-1]
    latest_season = int(latest_event["season"])
    latest_round = int(latest_event["round"])
    roster = frame[
        (frame["season"] == latest_season) & (frame["round"] == latest_round)
    ][["driver_id", "constructor_id"]].drop_duplicates("driver_id").copy()
    if roster.empty:
        raise ValueError("Could not derive a provisional roster from the latest event.")

    prediction_rows = []
    for row in roster.itertuples(index=False):
        item = {
            "season": args.season,
            "round": args.round,
            "driver_id": str(row.driver_id),
            "constructor_id": str(row.constructor_id),
            "circuit_id": args.circuit_id,
        }
        item.update(history_features(frame, str(row.driver_id)))
        prediction_rows.append(item)

    future = pd.DataFrame(prediction_rows)
    future = add_team_pace_columns(future, frame)
    future_features = prepare_features(future, numeric_used)
    future["predicted_qualifying_position"] = production.predict(future_features)
    future = future.sort_values(
        ["predicted_qualifying_position", "driver_id"]
    ).reset_index(drop=True)
    future.insert(0, "predicted_order", np.arange(1, len(future) + 1))
    future["predicted_position_rounded"] = future["predicted_qualifying_position"].round(1)
    future["event"] = f"{args.season} Round {args.round}"
    future["circuit_id"] = args.circuit_id

    output_cols = [
        "predicted_order", "driver_id", "constructor_id",
        "predicted_position_rounded", "predicted_qualifying_position",
        "event", "circuit_id",
    ]
    prediction_path = report_dir / f"round_{args.round}_{args.season}_qualifying_prediction.csv"
    future[output_cols].to_csv(prediction_path, index=False)

    report = {
        "event": {"season": args.season, "round": args.round, "circuit_id": args.circuit_id},
        "roster_source": f"latest completed event in {dataset_path.as_posix()}",
        "roster_source_event": {"season": latest_season, "round": latest_round},
        "roster_size": int(len(roster)),
        "training_rows": int(len(labeled)),
        "training_seasons": seasons,
        "selected_model": selected_kind,
        "feature_choice": feature_choice,
        "rolling_validation": validation,
        "chronological_holdout": {
            "season": int(holdout_season),
            "training_seasons": [s for s in seasons if s < holdout_season],
            "metrics": holdout_metrics,
        },
        "production_model": str(model_path),
        "prediction_csv": str(prediction_path),
        "caveats": [
            "The roster is copied from the latest completed event and must be checked against confirmed entries.",
            "Predicted qualifying order is not an official starting grid.",
            "The model does not know event-specific practice pace, weather, incidents, or penalties.",
            "Production model includes all completed qualifying labels available in the training table, including 2026 Round 17.",
        ],
    }
    report_path = report_dir / f"round_{args.round}_{args.season}_qualifying_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Selected model: {selected_kind}")
    print(f"Training rows with qualifying labels: {len(labeled):,}")
    print(f"Rolling validation seasons: {validation_seasons}")
    print(f"Chronological holdout ({holdout_season}): {holdout_metrics}")
    print(f"Roster source: {latest_season} Round {latest_round} ({len(roster)} drivers)")
    print(f"Model saved: {model_path}")
    print(f"Prediction saved: {prediction_path}")
    print(f"Report saved: {report_path}")
    print("\nPREDICTED QUALIFYING ORDER")
    print(future[["predicted_order", "driver_id", "constructor_id", "predicted_position_rounded"]].to_string(index=False))


if __name__ == "__main__":
    main()
