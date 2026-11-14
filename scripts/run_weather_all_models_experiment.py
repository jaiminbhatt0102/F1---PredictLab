"""Evaluate all six configured F1 models with experimental weather features.

This script DOES NOT write or replace production model artifacts.

Experiments:
1) Temperature-only: chronological test folds 2023-2026; 2026 is the newest forward-season evaluation.
2) Six weather variables: train on 2024, test on 2025 (exploratory due to one training season).

For each fold/target/model, compare the existing 12-feature baseline against the
same model with the specified weather feature(s) added. Reports Brier/log loss,
plus classification metrics. Missing weather remains missing and is imputed within
each training fold by the pipeline.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
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
REPORT_PATH = ROOT / "reports" / "weather_all_models_experiment.json"

BASE_NUMERIC = [
    "season", "round", "grid", "qualifying_position", "sprint_position",
    "sprint_points", "driver_prior_mean_finish_3",
    "driver_prior_mean_points_3", "driver_prior_race_count",
]
CATEGORICAL = ["driver_id", "constructor_id", "circuit_id"]
BASE_FEATURES = BASE_NUMERIC + CATEGORICAL
TARGETS = ["target_win", "target_podium"]
WEATHER_FEATURES = [
    "temperature_c", "relative_humidity_pct", "precipitation_mm",
    "cloud_cover_pct", "wind_speed_kmh", "wind_direction_deg",
]
JOIN_KEYS = ["season", "round", "circuit_id"]
MODEL_KINDS = [
    "prior_baseline",
    "logistic_regression",
    "random_forest",
    "extra_trees",
    "gradient_boosting",
    "hist_gradient_boosting",
]


def make_estimator(kind: str):
    if kind == "prior_baseline":
        return DummyClassifier(strategy="prior")
    if kind == "logistic_regression":
        return LogisticRegression(
            max_iter=2000, class_weight="balanced", random_state=42
        )
    if kind == "random_forest":
        return RandomForestClassifier(
            n_estimators=400, min_samples_leaf=3,
            class_weight="balanced_subsample", n_jobs=-1, random_state=42,
        )
    if kind == "extra_trees":
        return ExtraTreesClassifier(
            n_estimators=500, min_samples_leaf=3,
            class_weight="balanced", n_jobs=-1, random_state=42,
        )
    if kind == "gradient_boosting":
        return GradientBoostingClassifier(
            n_estimators=200, learning_rate=0.05, max_depth=2,
            min_samples_leaf=5, random_state=42,
        )
    if kind == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
            l2_regularization=1.0, random_state=42,
        )
    raise ValueError(f"Unknown model: {kind}")


def make_pipeline(kind: str, numeric_features: list[str]) -> Pipeline:
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    preprocess = ColumnTransformer([
        ("numeric", numeric, numeric_features),
        ("categorical", categorical, CATEGORICAL),
    ], remainder="drop")
    return Pipeline([
        ("preprocess", preprocess),
        ("model", make_estimator(kind)),
    ])


def calc_metrics(y_true: np.ndarray, prob: np.ndarray) -> dict[str, Any]:
    pred = (prob >= 0.5).astype(int)
    clipped = np.clip(prob, 1e-7, 1 - 1e-7)
    return {
        "rows": int(len(y_true)),
        "positive_count": int(y_true.sum()),
        "positive_rate": float(y_true.mean()),
        "accuracy_at_0_5": float(accuracy_score(y_true, pred)),
        "precision_at_0_5": float(precision_score(y_true, pred, zero_division=0)),
        "recall_at_0_5": float(recall_score(y_true, pred, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, prob)),
        "log_loss": float(log_loss(y_true, clipped, labels=[0, 1])),
        "roc_auc": (
            float(roc_auc_score(y_true, prob))
            if len(np.unique(y_true)) == 2 else None
        ),
    }


def run_comparison(
    data: pd.DataFrame,
    train_mask: pd.Series,
    test_mask: pd.Series,
    target: str,
    weather_features: list[str],
) -> dict[str, Any]:
    train = data.loc[train_mask].copy()
    test = data.loc[test_mask].copy()
    if train.empty or test.empty:
        raise ValueError(f"Empty partition for {target}")
    y_train = pd.to_numeric(train[target], errors="coerce")
    y_test = pd.to_numeric(test[target], errors="coerce")
    if y_train.isna().any() or y_test.isna().any():
        raise ValueError(f"Invalid target labels in {target}")
    y_train = y_train.astype(int).to_numpy()
    y_test = y_test.astype(int).to_numpy()
    if len(np.unique(y_train)) < 2:
        raise ValueError(f"Training partition has only one class for {target}")

    output: dict[str, Any] = {
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_seasons": sorted(train["season"].astype(int).unique().tolist()),
        "test_seasons": sorted(test["season"].astype(int).unique().tolist()),
        "models": {},
    }

    for kind in MODEL_KINDS:
        model_result: dict[str, Any] = {}
        for label, extra in (
            ("baseline", []),
            ("weather_enhanced", weather_features),
        ):
            numeric = BASE_NUMERIC + extra
            features = numeric + CATEGORICAL
            model = make_pipeline(kind, numeric)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                model.fit(train[features], y_train)
            prob = model.predict_proba(test[features])[:, 1]
            model_result[label] = calc_metrics(y_test, prob)
        output["models"][kind] = model_result
        print(
            f"    {kind}: "
            f"Brier baseline={model_result['baseline']['brier_score']:.5f}, "
            f"weather={model_result['weather_enhanced']['brier_score']:.5f}; "
            f"logloss baseline={model_result['baseline']['log_loss']:.5f}, "
            f"weather={model_result['weather_enhanced']['log_loss']:.5f}"
        )
    return output


def main() -> None:
    base = pd.read_csv(TRAINING_PATH, low_memory=False)
    weather = pd.read_csv(WEATHER_PATH, low_memory=False)

    for frame in (base, weather):
        frame["season"] = pd.to_numeric(frame["season"], errors="coerce")
        frame["round"] = pd.to_numeric(frame["round"], errors="coerce")
        frame["circuit_id"] = frame["circuit_id"].astype("string").str.strip()

    base = base.dropna(subset=["season", "round"]).copy()
    base["season"] = base["season"].astype(int)
    base["round"] = base["round"].astype(int)
    weather = weather.dropna(subset=["season", "round"]).copy()
    weather["season"] = weather["season"].astype(int)
    weather["round"] = weather["round"].astype(int)

    if weather.duplicated(JOIN_KEYS).any():
        raise ValueError("Weather dataset contains duplicate join keys")
    for col in WEATHER_FEATURES:
        weather[col] = pd.to_numeric(weather[col], errors="coerce")

    merged = base.merge(
        weather[JOIN_KEYS + WEATHER_FEATURES],
        on=JOIN_KEYS,
        how="left",
        validate="many_to_one",
    )
    for col in WEATHER_FEATURES:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")

    # Experimental data files only; never write to the production training CSV.
    features_dir = ROOT / "data" / "features"
    features_dir.mkdir(parents=True, exist_ok=True)
    temp_path = features_dir / "race_training_weather_temperature_experimental.csv"
    six_path = features_dir / "race_training_weather_six_variable_experimental.csv"
    temperature_data = merged.loc[merged["season"].isin([2022, 2023, 2024, 2025, 2026])].copy()
    six_data = merged.loc[merged["season"].isin([2024, 2025])].copy()
    temperature_data.to_csv(temp_path, index=False, na_rep="")
    six_data.to_csv(six_path, index=False, na_rep="")

    report: dict[str, Any] = {
        "production_artifacts_modified": False,
        "model_kinds": MODEL_KINDS,
        "weather_source": "Open-Meteo Previous Runs API",
        "validation_notes": [
            "2026 is the newest forward-season evaluation fold and should be treated as the primary current-season check.",
            "Do not select models using 2026 results; use earlier chronological folds for selection and report 2026 as an external forward check.",
            "The six-variable experiment remains exploratory because it tests 2025 after training only on 2024.",
            "This script evaluates candidates only and does not write or replace production model artifacts."
        ],
        "temperature_experiment": {
            "weather_features": ["temperature_c"],
            "dataset": str(temp_path.relative_to(ROOT)),
            "training_evaluation_seasons": [2022, 2023, 2024, 2025, 2026],
            "folds": {},
        },
        "six_variable_experiment": {
            "weather_features": WEATHER_FEATURES,
            "dataset": str(six_path.relative_to(ROOT)),
            "evaluation": {},
            "caveat": (
                "Train 2024 and test 2025. This is exploratory: one training season "
                "and only 24 distinct race-weather observations in the training season."
            ),
        },
        "join_diagnostics": {
            "base_rows": int(len(base)),
            "merged_rows": int(len(merged)),
            "unique_races_with_temperature": int(
                merged.loc[merged["temperature_c"].notna(), JOIN_KEYS]
                .drop_duplicates().shape[0]
            ),
        },
    }

    for season in [2023, 2024, 2025, 2026]:
        fold: dict[str, Any] = {"test_season": season, "targets": {}}
        for target in TARGETS:
            print(f"\nTemperature experiment | test={season} | target={target}")
            fold["targets"][target] = run_comparison(
                temperature_data,
                temperature_data["season"] < season,
                temperature_data["season"] == season,
                target,
                ["temperature_c"],
            )
        report["temperature_experiment"]["folds"][str(season)] = fold

    for target in TARGETS:
        print(f"\nSix-variable experiment | train=2024 test=2025 | target={target}")
        report["six_variable_experiment"]["evaluation"][target] = run_comparison(
            six_data,
            six_data["season"] == 2024,
            six_data["season"] == 2025,
            target,
            WEATHER_FEATURES,
        )

    report["weather_coverage_by_season"] = {}
    for season, group in weather.groupby("season"):
        report["weather_coverage_by_season"][str(int(season))] = {
            "race_count": int(len(group)),
            "non_null_races": {
                col: int(group[col].notna().sum()) for col in WEATHER_FEATURES
            },
        }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== ALL-MODEL WEATHER EXPERIMENT COMPLETE ===")
    print(f"Report: {REPORT_PATH}")
    print(f"Temperature dataset: {temp_path}")
    print(f"Six-variable dataset: {six_path}")
    print("Production training data and model artifacts were not modified.")


if __name__ == "__main__":
    main()
