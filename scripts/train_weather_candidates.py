"""Train isolated experimental temperature-aware F1 models.

Does not modify production model artifacts. Candidate features match the existing
12 race features plus temperature_c used in the historical weather experiment.
"""
from __future__ import annotations
import json
from pathlib import Path
import warnings
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/features/race_training_weather_temperature_experimental.csv"
OUT = ROOT / "models/weather_candidates"
REPORT = ROOT / "reports/weather_candidate_training.json"

NUMERIC = [
    "season", "round", "grid", "qualifying_position", "sprint_position",
    "sprint_points", "driver_prior_mean_finish_3", "driver_prior_mean_points_3",
    "driver_prior_race_count", "temperature_c",
]
CATEGORICAL = ["driver_id", "constructor_id", "circuit_id"]
TARGETS = ["target_win", "target_podium"]
KINDS = {
    "hist_gradient_boosting": lambda: HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
        l2_regularization=1.0, random_state=42
    ),
    "random_forest": lambda: RandomForestClassifier(
        n_estimators=400, min_samples_leaf=3,
        class_weight="balanced_subsample", n_jobs=-1, random_state=42
    ),
}

def make_pipeline(kind: str) -> Pipeline:
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    prep = ColumnTransformer([
        ("numeric", numeric, NUMERIC),
        ("categorical", categorical, CATEGORICAL),
    ], remainder="drop")
    return Pipeline([("preprocess", prep), ("model", KINDS[kind]())])

def main() -> None:
    if not DATA.exists():
        raise FileNotFoundError(
            f"Missing {DATA}. Run scripts/run_weather_all_models_experiment.py first."
        )
    df = pd.read_csv(DATA, low_memory=False)
    required = set(NUMERIC + CATEGORICAL + TARGETS)
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Experimental training table missing columns: {missing}")
    df["season"] = pd.to_numeric(df["season"], errors="coerce")
    df = df.dropna(subset=["season"]).copy()
    df["season"] = df["season"].astype(int)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in CATEGORICAL:
        df[c] = df[c].fillna("unknown").astype(str).replace("", "unknown")
    df = df.replace([np.inf, -np.inf], np.nan)
    # The temperature-only experiment covers 2022-2026. Fit on all available
    # completed rows only after the pre-2026 selection review.
    seasons = sorted(df["season"].unique().astype(int).tolist())
    if not {2022, 2023, 2024, 2025}.issubset(set(seasons)):
        raise ValueError(f"Expected historical seasons 2022-2025; found {seasons}")
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "dataset": str(DATA.relative_to(ROOT)),
        "rows": int(len(df)),
        "seasons": seasons,
        "features": NUMERIC + CATEGORICAL,
        "targets": TARGETS,
        "candidates": {},
        "production_artifacts_modified": False,
        "selection_note": (
            "HistGradientBoosting had the lowest mean Brier score across 2023-2025 "
            "temperature folds for both targets. RandomForest is also trained as a "
            "comparison candidate because the 2026 forward win fold was mixed. "
            "No candidate is promoted automatically."
        ),
        "timing_contract": (
            "Historical temperature comes from Open-Meteo Previous Runs previous_day1 "
            "(forecast value at a 24-hour lead). For inference, use a forecast snapshot "
            "approximately 18-30 hours before scheduled race start."
        ),
    }
    for target in TARGETS:
        y = pd.to_numeric(df[target], errors="coerce")
        if y.isna().any() or not y.isin([0, 1]).all() or y.nunique() != 2:
            raise ValueError(f"{target} must be complete and binary with both classes")
        summary["candidates"][target] = {}
        for kind in KINDS:
            model = make_pipeline(kind)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                model.fit(df[NUMERIC + CATEGORICAL], y.astype(int))
            path = OUT / f"{target}_temperature_{kind}.joblib"
            payload = {
                "pipeline": model,
                "features": NUMERIC + CATEGORICAL,
                "target": target,
                "model_kind": kind,
                "weather_features": ["temperature_c"],
                "trained_through_season": max(seasons),
                "prediction_checkpoint": "post_qualifying_pre_race",
                "experimental": True,
                "timing_contract": "forecast snapshot 18-30 hours before race start",
            }
            joblib.dump(payload, path)
            summary["candidates"][target][kind] = {
                "artifact": str(path.relative_to(ROOT)),
                "rows": int(len(df)),
                "trained_through_season": int(max(seasons)),
            }
            print(f"Saved experimental candidate: {path}")
    REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Training report: {REPORT}")
    print("Production models were not changed.")

if __name__ == "__main__":
    main()
