"""Run isolated F1 weather-feature experiments without touching production artifacts.

Creates:
  data/features/race_training_weather_temperature_experimental.csv
  data/features/race_training_weather_six_variable_experimental.csv
  reports/weather_model_experiment.json

Temperature experiment:
  Rolling evaluation on 2023, 2024, and 2025; train only on earlier seasons.
Six-variable experiment:
  Train on 2024, evaluate on 2025 (exploratory due to only one training season).

Both compare the existing feature set against the same feature set plus weather,
using GradientBoostingClassifier for an apples-to-apples feature comparison.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
TRAINING_PATH = ROOT / "data" / "features" / "race_training.csv"
WEATHER_PATH = ROOT / "data" / "processed" / "weather_forecasts_experimental.csv"
TEMP_DATASET_PATH = ROOT / "data" / "features" / "race_training_weather_temperature_experimental.csv"
SIX_DATASET_PATH = ROOT / "data" / "features" / "race_training_weather_six_variable_experimental.csv"
REPORT_PATH = ROOT / "reports" / "weather_model_experiment.json"

BASE_NUMERIC = [
    "season", "round", "grid", "qualifying_position", "sprint_position",
    "sprint_points", "driver_prior_mean_finish_3",
    "driver_prior_mean_points_3", "driver_prior_race_count",
]
CATEGORICAL = ["driver_id", "constructor_id", "circuit_id"]
TARGETS = ["target_win", "target_podium"]
WEATHER_COLUMNS = [
    "temperature_c", "relative_humidity_pct", "precipitation_mm",
    "cloud_cover_pct", "wind_speed_kmh", "wind_direction_deg",
]
JOIN_KEYS = ["season", "round", "circuit_id"]


def build_pipeline(numeric_features: list[str]) -> Pipeline:
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
        ("categorical", categorical, CATEGORICAL),
    ], remainder="drop")
    model = GradientBoostingClassifier(
        n_estimators=200, learning_rate=0.05, max_depth=2,
        min_samples_leaf=5, random_state=42,
    )
    return Pipeline([("preprocess", prep), ("model", model)])


def metrics(y_true: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    prediction = (probability >= 0.5).astype(int)
    clipped = np.clip(probability, 1e-7, 1 - 1e-7)
    return {
        "rows": int(len(y_true)),
        "positive_count": int(y_true.sum()),
        "positive_rate": float(y_true.mean()),
        "accuracy_at_0_5": float(accuracy_score(y_true, prediction)),
        "precision_at_0_5": float(precision_score(y_true, prediction, zero_division=0)),
        "recall_at_0_5": float(recall_score(y_true, prediction, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, probability)),
        "log_loss": float(log_loss(y_true, clipped, labels=[0, 1])),
        "roc_auc": (
            float(roc_auc_score(y_true, probability))
            if len(np.unique(y_true)) == 2 else None
        ),
    }


def run_pair(
    frame: pd.DataFrame,
    train_mask: pd.Series,
    test_mask: pd.Series,
    target: str,
    base_numeric: list[str],
    weather_numeric: list[str],
) -> dict[str, Any]:
    train = frame.loc[train_mask].copy()
    test = frame.loc[test_mask].copy()
    if train.empty or test.empty:
        raise ValueError(f"Empty train/test partition for {target}")
    y_train = pd.to_numeric(train[target], errors="coerce")
    y_test = pd.to_numeric(test[target], errors="coerce")
    if y_train.isna().any() or y_test.isna().any():
        raise ValueError(f"Missing target labels in {target}")
    if y_train.nunique() < 2:
        raise ValueError(f"Training partition has only one class for {target}")

    result: dict[str, Any] = {
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_seasons": sorted(train["season"].astype(int).unique().tolist()),
        "test_seasons": sorted(test["season"].astype(int).unique().tolist()),
        "baseline": {},
        "weather_enhanced": {},
    }
    for label, numeric in (
        ("baseline", base_numeric),
        ("weather_enhanced", base_numeric + weather_numeric),
    ):
        feature_columns = numeric + CATEGORICAL
        model = build_pipeline(numeric)
        model.fit(train[feature_columns], y_train.astype(int).to_numpy())
        probability = model.predict_proba(test[feature_columns])[:, 1]
        result[label] = metrics(y_test.astype(int).to_numpy(), probability)
    return result


BASE_FEATURES = BASE_NUMERIC + CATEGORICAL


def main() -> None:
    if not TRAINING_PATH.exists():
        raise FileNotFoundError(f"Missing {TRAINING_PATH}")
    if not WEATHER_PATH.exists():
        raise FileNotFoundError(f"Missing {WEATHER_PATH}")

    base = pd.read_csv(TRAINING_PATH, low_memory=False)
    weather = pd.read_csv(WEATHER_PATH, low_memory=False)
    required_base = set(BASE_FEATURES + TARGETS + JOIN_KEYS)
    missing = sorted(required_base - set(base.columns))
    if missing:
        raise ValueError(f"Base training dataset missing columns: {missing}")
    missing_weather = sorted(set(JOIN_KEYS + WEATHER_COLUMNS) - set(weather.columns))
    if missing_weather:
        raise ValueError(f"Weather dataset missing columns: {missing_weather}")

    for frame in (base, weather):
        frame["season"] = pd.to_numeric(frame["season"], errors="coerce")
        frame["round"] = pd.to_numeric(frame["round"], errors="coerce")
        frame["circuit_id"] = frame["circuit_id"].astype("string").str.strip()

    weather["season"] = weather["season"].astype(int)
    weather["round"] = weather["round"].astype(int)
    if weather.duplicated(JOIN_KEYS).any():
        raise ValueError("Weather file has duplicate season/round/circuit keys")
    base["season"] = pd.to_numeric(base["season"], errors="coerce")
    base["round"] = pd.to_numeric(base["round"], errors="coerce")
    base = base.dropna(subset=["season", "round"]).copy()
    base["season"] = base["season"].astype(int)
    base["round"] = base["round"].astype(int)

    weather_subset = weather[JOIN_KEYS + WEATHER_COLUMNS].copy()
    merged = base.merge(
        weather_subset, on=JOIN_KEYS, how="left", validate="many_to_one",
        indicator="_weather_merge",
    )
    merged["weather_match"] = merged["_weather_merge"].eq("both")
    merged.drop(columns=["_weather_merge"], inplace=True)
    for col in WEATHER_COLUMNS:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")

    # Save complete experimental data separately; production CSV is not changed.
    TEMP_DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_frame = merged.copy()
    temp_frame.to_csv(TEMP_DATASET_PATH, index=False, na_rep="")
    six_frame = merged[merged["season"].isin([2024, 2025])].copy()
    six_frame.to_csv(SIX_DATASET_PATH, index=False, na_rep="")

    output: dict[str, Any] = {
        "model": "GradientBoostingClassifier (same settings for baseline and enhanced)",
        "production_artifacts_modified": False,
        "join_keys": JOIN_KEYS,
        "weather_source": "Open-Meteo Previous Runs API",
        "temperature_experiment": {
            "dataset": str(TEMP_DATASET_PATH.relative_to(ROOT)),
            "weather_feature": "temperature_c",
            "folds": {},
        },
        "six_variable_experiment": {
            "dataset": str(SIX_DATASET_PATH.relative_to(ROOT)),
            "weather_features": WEATHER_COLUMNS,
            "evaluation": {},
            "caveat": (
                "Trained on 2024 and tested on 2025. Only one season of training "
                "data and 24 distinct training race-weather observations; exploratory only."
            ),
        },
        "join_diagnostics": {
            "base_rows": int(len(base)),
            "merged_rows": int(len(merged)),
            "rows_with_weather_match": int(merged["weather_match"].sum()),
            "unique_races_with_temperature": int(
                merged.loc[merged["temperature_c"].notna(), JOIN_KEYS]
                .drop_duplicates().shape[0]
            ),
        },
    }

    # Rolling season comparisons; 2025 remains the final holdout.
    for season in [2023, 2024, 2025]:
        train_mask = merged["season"] < season
        test_mask = merged["season"] == season
        fold: dict[str, Any] = {
            "train_seasons": sorted(merged.loc[train_mask, "season"].unique().astype(int).tolist()),
            "test_season": season,
            "targets": {},
        }
        for target in TARGETS:
            fold["targets"][target] = run_pair(
                merged, train_mask, test_mask, target,
                BASE_NUMERIC, ["temperature_c"],
            )
        output["temperature_experiment"]["folds"][str(season)] = fold

    # All six variables: use 2024 for training and 2025 as the untouched test year.
    # Restrict to the two seasons where all six fields were available, but do not
    # require complete rows for the baseline; enhanced pipeline imputes any blanks.
    for target in TARGETS:
        output["six_variable_experiment"]["evaluation"][target] = run_pair(
            six_frame,
            six_frame["season"] == 2024,
            six_frame["season"] == 2025,
            target,
            BASE_NUMERIC,
            WEATHER_COLUMNS,
        )

    # Coverage is race-level; do not mistake repeated per-driver rows for new weather observations.
    output["weather_coverage_by_season"] = {}
    for season, group in weather.groupby("season"):
        output["weather_coverage_by_season"][str(int(season))] = {
            "races": int(len(group)),
            "non_null_races": {
                col: int(group[col].notna().sum()) for col in WEATHER_COLUMNS
            },
        }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("=== WEATHER EXPERIMENT COMPLETE ===")
    print(f"Temperature dataset: {TEMP_DATASET_PATH}")
    print(f"Six-variable dataset: {SIX_DATASET_PATH}")
    print(f"Report: {REPORT_PATH}")
    print("\nJoin diagnostics:")
    print(json.dumps(output["join_diagnostics"], indent=2))
    print("\nTemperature experiment (Brier/log loss; lower is better):")
    for season, fold in output["temperature_experiment"]["folds"].items():
        print(f"Test season {season}")
        for target, result in fold["targets"].items():
            print(
                f"  {target}: baseline Brier={result['baseline']['brier_score']:.5f}, "
                f"weather Brier={result['weather_enhanced']['brier_score']:.5f}; "
                f"baseline logloss={result['baseline']['log_loss']:.5f}, "
                f"weather logloss={result['weather_enhanced']['log_loss']:.5f}"
            )
    print("\nSix-variable experiment (train 2024, test 2025):")
    for target, result in output["six_variable_experiment"]["evaluation"].items():
        print(
            f"  {target}: baseline Brier={result['baseline']['brier_score']:.5f}, "
            f"six-variable Brier={result['weather_enhanced']['brier_score']:.5f}; "
            f"baseline logloss={result['baseline']['log_loss']:.5f}, "
            f"six-variable logloss={result['weather_enhanced']['log_loss']:.5f}"
        )
    print("\nNo production models or production training data were modified.")


if __name__ == "__main__":
    main()
