"""Train the sprint finishing-position model.

A sprint is predicted *before the sprint*, so only information that exists at that
moment may be used: earlier races, earlier sprints, the driver's team and the circuit.
Nothing from the same sprint (grid, result) or from the same weekend's race is used.

Validation is chronological (train on earlier seasons, test on a later one). A simple
"recent form" baseline competes with the learned models; the baseline wins if they do
not beat it, so the production model is never worse than just using recent results.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC = ["season", "round", "driver_prior_mean_finish_3", "driver_prior_mean_points_3", "driver_prior_race_count"]
CATEGORICAL = ["driver_id", "constructor_id", "circuit_id"]
FEATURES = NUMERIC + CATEGORICAL
TARGET = "sprint_position"


class RecentFormBaseline(BaseEstimator, RegressorMixin):
    """Predict a driver's average finish over their last three races."""

    def fit(self, X: pd.DataFrame, y: Any = None) -> "RecentFormBaseline":
        values = pd.to_numeric(X["driver_prior_mean_finish_3"], errors="coerce")
        self.fallback_ = float(values.median()) if values.notna().any() else 10.5
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        values = pd.to_numeric(X["driver_prior_mean_finish_3"], errors="coerce")
        return values.fillna(self.fallback_).to_numpy(dtype=float)


def _preprocessor(dense: bool) -> ColumnTransformer:
    return ColumnTransformer([
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=not dense), CATEGORICAL),
    ])


def make_pipeline(kind: str) -> Pipeline | RecentFormBaseline:
    if kind == "recent_form":
        return RecentFormBaseline()
    if kind == "ridge":
        return Pipeline([("prep", _preprocessor(False)), ("model", Ridge(alpha=5.0))])
    if kind == "gradient_boosting":
        return Pipeline([("prep", _preprocessor(True)), ("model", HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=120, random_state=7))])
    raise ValueError(f"Unknown sprint model kind: {kind}")


KINDS = ["recent_form", "ridge", "gradient_boosting"]


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[FEATURES].copy()
    for col in CATEGORICAL:
        out[col] = out[col].fillna("unknown").astype(str)
    for col in NUMERIC:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.replace([np.inf, -np.inf], np.nan)


def load_sprint_frame(processed_dir: Path, dataset_path: Path) -> pd.DataFrame:
    parts = []
    for path in sorted(Path(processed_dir).glob("*_sprint_normalized.csv")):
        part = pd.read_csv(path)
        parts.append(part[["season", "round", "driver_id", "constructor_id", "circuit_id", "position"]])
    if not parts:
        raise ValueError("No normalized sprint results were found.")
    sprints = pd.concat(parts, ignore_index=True)
    sprints[TARGET] = pd.to_numeric(sprints["position"], errors="coerce")
    sprints = sprints.dropna(subset=[TARGET]).drop(columns="position")
    race = pd.read_csv(dataset_path)
    prior = race[["season", "round", "driver_id", "driver_prior_mean_finish_3", "driver_prior_mean_points_3", "driver_prior_race_count"]]
    frame = sprints.merge(prior, on=["season", "round", "driver_id"], how="left")
    frame["season"] = frame["season"].astype(int)
    frame["round"] = frame["round"].astype(int)
    return frame.sort_values(["season", "round", "driver_id"]).reset_index(drop=True)


def _mae(kind: str, train: pd.DataFrame, test: pd.DataFrame) -> float:
    model = make_pipeline(kind)
    model.fit(prepare(train), train[TARGET])
    return float(mean_absolute_error(test[TARGET], model.predict(prepare(test))))


def train_sprint_model(
    processed_dir: str | Path = "data/processed",
    dataset_path: str | Path = "data/features/race_training.csv",
    model_dir: str | Path = "models",
    report_path: str | Path = "reports/sprint_model_evaluation.json",
) -> dict[str, Any]:
    frame = load_sprint_frame(Path(processed_dir), Path(dataset_path))
    seasons = sorted(frame["season"].unique().tolist())
    if len(seasons) < 3:
        raise ValueError("Not enough sprint seasons to validate a sprint model.")
    holdout = seasons[-2]
    validation = seasons[1:-2] or [seasons[1]]
    rolling: dict[str, list[dict]] = {k: [] for k in KINDS}
    for season in validation:
        train, test = frame[frame["season"] < season], frame[frame["season"] == season]
        if train.empty or test.empty:
            continue
        for kind in KINDS:
            rolling[kind].append({"season": int(season), "rows": int(len(test)), "mae_positions": _mae(kind, train, test)})
    means = {k: float(np.mean([f["mae_positions"] for f in v])) for k, v in rolling.items() if v}
    selected = min(means, key=means.get)
    h_train, h_test = frame[frame["season"] < holdout], frame[frame["season"] == holdout]
    holdout_metrics = {k: {"rows": int(len(h_test)), "mae_positions": _mae(k, h_train, h_test)} for k in {selected, "recent_form"}}

    production = make_pipeline(selected)
    production.fit(prepare(frame), frame[TARGET])
    last = frame.sort_values(["season", "round"]).iloc[-1]
    artifact = {
        "pipeline": production,
        "features": FEATURES,
        "target": TARGET,
        "model_kind": selected,
        "trained_through_event": {"season": int(last["season"]), "round": int(last["round"])},
        "prediction_checkpoint": "pre_sprint",
        "note": "Predicted sprint order from past form only. Not a sprint grid or result.",
    }
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_dir / "sprint_position_selected.joblib")
    report = {
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(frame)),
        "training_seasons": [int(s) for s in seasons],
        "validation_seasons": [int(s) for s in validation],
        "holdout_season": int(holdout),
        "selected_model": selected,
        "rolling_validation": {k: {"mean_mae_positions": means.get(k), "folds": v} for k, v in rolling.items()},
        "holdout": holdout_metrics,
        "note": "Chronological validation only. The recent-form baseline is selected if no learned model beats it.",
    }
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = train_sprint_model()
    print(f"Sprint model: {result['selected_model']} | holdout {result['holdout_season']} | rows {result['training_rows']}")
