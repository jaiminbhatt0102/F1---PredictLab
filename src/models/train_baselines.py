"""Leakage-aware chronological training and evaluation for F1 win/podium models."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import joblib
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

from src.features.extra_features import EXTRA_FEATURES, QUALI_GAP_FEATURES, TEAM_PACE_FEATURES, usable_extra_features
from src.models.probabilities import normalize_podium, normalize_win


NUMERIC_FEATURES = [
    "season",
    "round",
    "grid",
    "qualifying_position",
    "sprint_position",
    "sprint_points",
    "driver_prior_mean_finish_3",
    "driver_prior_mean_points_3",
    "driver_prior_race_count",
]
CATEGORICAL_FEATURES = ["driver_id", "constructor_id", "circuit_id"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGETS = ["target_win", "target_podium"]
# Chosen by chronological validation (reports/feature_experiment.json): each season back counts 40% less.
RECENCY_DECAY = 0.6
PROBABILITY_ADJUSTMENT = "normalized_per_race"
MODEL_KINDS = (
    "prior_baseline",
    "logistic_regression",
    "random_forest",
    "extra_trees",
    "gradient_boosting",
    "hist_gradient_boosting",
)
FORBIDDEN_FEATURES = {
    "finish_position", "race_position_num", "race_points", "race_points_num",
    "race_status", "position_text", "time", "milliseconds", "fastest_lap_rank",
    "fastest_lap_number", "fastest_lap_time", "target_win", "target_podium",
}


def _make_pipeline(kind: str, numeric_features: list[str] | None = None) -> Pipeline:
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

    if kind == "prior_baseline":
        estimator = DummyClassifier(strategy="prior")
    elif kind == "logistic_regression":
        estimator = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)
    elif kind == "random_forest":
        estimator = RandomForestClassifier(
            n_estimators=400, min_samples_leaf=3, class_weight="balanced_subsample",
            n_jobs=-1, random_state=42,
        )
    elif kind == "extra_trees":
        estimator = ExtraTreesClassifier(
            n_estimators=500, min_samples_leaf=3, class_weight="balanced",
            n_jobs=-1, random_state=42,
        )
    elif kind == "gradient_boosting":
        estimator = GradientBoostingClassifier(
            n_estimators=200, learning_rate=0.05, max_depth=2,
            min_samples_leaf=5, random_state=42,
        )
    elif kind == "hist_gradient_boosting":
        estimator = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
            l2_regularization=1.0, random_state=42,
        )
    else:
        raise ValueError(f"Unknown model kind: {kind}")
    return Pipeline([("preprocess", prep), ("model", estimator)])


def _safe_metrics(
    y_true: np.ndarray, probability: np.ndarray, threshold: float = 0.5
) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=int)
    probability = np.asarray(probability, dtype=float)
    pred = (probability >= threshold).astype(int)
    result: dict[str, Any] = {
        "rows": int(len(y_true)),
        "positive_count": int(y_true.sum()),
        "positive_rate": float(y_true.mean()) if len(y_true) else None,
        "accuracy_at_0_5": float(accuracy_score(y_true, pred)),
        "precision_at_0_5": float(precision_score(y_true, pred, zero_division=0)),
        "recall_at_0_5": float(recall_score(y_true, pred, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, probability)),
    }
    clipped = np.clip(probability, 1e-7, 1 - 1e-7)
    result["log_loss"] = float(log_loss(y_true, clipped, labels=[0, 1]))
    result["roc_auc"] = (
        float(roc_auc_score(y_true, probability))
        if len(np.unique(y_true)) == 2 else None
    )
    return result


def _prepare_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Prepare model inputs without using post-race information."""
    prepared = frame.copy()
    for col in CATEGORICAL_FEATURES:
        prepared[col] = prepared[col].fillna("unknown").astype(str)
    for col in NUMERIC_FEATURES + [c for c in EXTRA_FEATURES if c in prepared.columns]:
        prepared[col] = pd.to_numeric(prepared[col], errors="coerce")
    return prepared


def recency_weights(frame: pd.DataFrame, newest_season: int) -> np.ndarray:
    """Recent seasons count more: the 2026 rule changes make old seasons less relevant."""
    return RECENCY_DECAY ** (newest_season - frame["season"]).to_numpy(dtype=float)


def adjust_per_race(frame: pd.DataFrame, probability: np.ndarray, target: str) -> np.ndarray:
    """Make chances add up to 1 (win) or 3 (podium) within each race."""
    fn = normalize_win if target == "target_win" else normalize_podium
    out = np.asarray(probability, dtype=float).copy()
    for _, idx in frame.groupby(["season", "round"]).indices.items():
        out[idx] = fn(out[idx])
    return out


def _fit(model: Pipeline, train: pd.DataFrame, features: list[str], target: str, newest_season: int) -> Pipeline:
    kwargs = {"model__sample_weight": recency_weights(train, newest_season)} if hasattr(model, "steps") else {}
    model.fit(train[features], _checked_target(train, target), **kwargs)
    return model


def _score(model: Pipeline, frame: pd.DataFrame, features: list[str], target: str) -> dict[str, Any]:
    y = _checked_binary_values(frame, target)
    probability = adjust_per_race(frame, model.predict_proba(frame[features])[:, 1], target)
    return _safe_metrics(y, probability)


def choose_numeric_features(prepared: pd.DataFrame, validation_seasons: list[int], available_extras: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Pick the input set that scores best on the validation seasons.

    Candidates: the original inputs, plus team pace, plus qualifying time gaps (only when enough
    lap-time data exists). The simplest set wins ties. The holdout season is never looked at here.
    """
    team = [c for c in TEAM_PACE_FEATURES if c in available_extras]
    gaps = [c for c in QUALI_GAP_FEATURES if c in available_extras]
    candidates: dict[str, list[str]] = {"original inputs": list(NUMERIC_FEATURES)}
    if team:
        candidates["plus team pace"] = NUMERIC_FEATURES + team
    if team and gaps:
        candidates["plus team pace and qualifying gaps"] = NUMERIC_FEATURES + team + gaps
    scores: dict[str, float] = {}
    for name, numeric in candidates.items():
        features = numeric + CATEGORICAL_FEATURES
        total = []
        for target in TARGETS:
            for season in validation_seasons:
                train, test = prepared[prepared["season"] < season], prepared[prepared["season"] == season]
                if train.empty or test.empty:
                    continue
                model = _fit(_make_pipeline("hist_gradient_boosting", numeric), train, features, target, season - 1)
                total.append(_score(model, test, features, target)["brier_score"])
        scores[name] = float(np.mean(total))
    best = min(scores, key=lambda n: (round(scores[n], 5), len(candidates[n])))
    return candidates[best], {"chosen": best, "validation_brier_by_option": scores, "features": candidates[best]}


def _checked_target(frame: pd.DataFrame, target: str) -> np.ndarray:
    """Reject missing, non-binary, or single-class labels."""
    values = pd.to_numeric(frame[target], errors="coerce")
    if values.isna().any():
        raise ValueError(
            f"{target} contains {int(values.isna().sum())} missing or invalid labels"
        )
    if not values.isin([0, 1]).all():
        raise ValueError(f"{target} must contain only binary labels 0 and 1")
    labels = values.astype(int).to_numpy()
    if len(np.unique(labels)) < 2:
        raise ValueError(f"{target} contains only one class in this partition")
    return labels


def _checked_binary_values(frame: pd.DataFrame, target: str) -> np.ndarray:
    """Validate labels for scoring; a one-class scoring season is permitted."""
    values = pd.to_numeric(frame[target], errors="coerce")
    if values.isna().any():
        raise ValueError(
            f"{target} contains {int(values.isna().sum())} missing or invalid labels"
        )
    if not values.isin([0, 1]).all():
        raise ValueError(f"{target} must contain only binary labels 0 and 1")
    return values.astype(int).to_numpy()


def _aggregate_fold_metrics(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Average numeric metrics across validation seasons and retain fold details."""
    metric_keys = [
        "accuracy_at_0_5", "precision_at_0_5", "recall_at_0_5",
        "brier_score", "log_loss", "roc_auc",
    ]
    aggregate: dict[str, Any] = {
        "folds": len(folds),
        "rows": int(sum(fold["rows"] for fold in folds)),
        "positive_count": int(sum(fold["positive_count"] for fold in folds)),
        "positive_rate": (
            float(sum(fold["positive_count"] for fold in folds) /
                  sum(fold["rows"] for fold in folds))
            if sum(fold["rows"] for fold in folds) else None
        ),
        "by_season": {str(fold["season"]): fold["metrics"] for fold in folds},
    }
    for key in metric_keys:
        values = [fold["metrics"][key] for fold in folds if fold["metrics"][key] is not None]
        aggregate[key] = float(np.mean(values)) if values else None
    return aggregate


def _select_model(model_summary: dict[str, dict[str, Any]]) -> str:
    """Select by lowest mean Brier score, then log loss, with stable model-name tie-break."""
    def key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, str]:
        name, metrics = item
        brier = metrics.get("brier_score")
        loss = metrics.get("log_loss")
        return (
            float(brier) if brier is not None else float("inf"),
            float(loss) if loss is not None else float("inf"),
            name,
        )
    return min(model_summary.items(), key=key)[0]


def _commit_staged_files(staged_to_destination: dict[Path, Path], backup_dir: Path) -> None:
    """Replace a set of files as one recoverable operation if a replacement fails."""
    moved_originals: dict[Path, Path] = {}
    installed: list[Path] = []
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, destination in enumerate(staged_to_destination.values()):
            if destination.exists():
                backup = backup_dir / f"original_{index}_{destination.name}"
                os.replace(destination, backup)
                moved_originals[destination] = backup
        for staged, destination in staged_to_destination.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, destination)
            installed.append(destination)
    except Exception:
        for destination in reversed(installed):
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        for destination, backup in moved_originals.items():
            if backup.exists():
                os.replace(backup, destination)
        raise


def train_and_evaluate(
    dataset_path: str | Path = "data/features/race_training.csv",
    model_dir: str | Path = "models",
    report_path: str | Path = "reports/model_evaluation.json",
) -> dict[str, Any]:
    """Run rolling validation, evaluate the 2025 holdout, then fit production models.

    Model selection uses only the rolling validation seasons before 2025. The final
    holdout trains on seasons before 2025 and tests on 2025. Only after selection
    and holdout evaluation are complete are production candidates fitted on all
    available seasons (including 2026, when present).
    """
    frame = pd.read_csv(dataset_path)
    required = set(FEATURES + TARGETS + ["season"])
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Training dataset is missing required columns: {missing}")
    if FORBIDDEN_FEATURES.intersection(FEATURES):
        raise RuntimeError("Leakage guard: a forbidden post-race field is in FEATURES")

    frame = frame.replace([np.inf, -np.inf], np.nan)
    frame["season"] = pd.to_numeric(frame["season"], errors="coerce")
    frame = frame.dropna(subset=["season"]).copy()
    frame["season"] = frame["season"].astype(int)
    seasons = sorted(int(s) for s in frame["season"].unique())
    if len(seasons) < 3:
        raise ValueError(f"Need at least 3 seasons for chronological evaluation; found {seasons}")

    # The project holdout is fixed at 2025 whenever that season is available.
    # Do not silently move the holdout to 2026 and accidentally score on partial data.
    holdout_season = 2025 if 2025 in seasons else seasons[-1]
    pre_holdout_seasons = [season for season in seasons if season < holdout_season]
    holdout_seasons = [season for season in seasons if season == holdout_season]
    if len(pre_holdout_seasons) < 3 or not holdout_seasons:
        raise ValueError(
            f"Need at least 3 pre-holdout seasons and holdout season {holdout_season}; "
            f"found pre-holdout seasons {pre_holdout_seasons}"
        )

    # Use the latest three seasons before the holdout as chronological validation folds.
    validation_seasons = pre_holdout_seasons[-3:]
    prepared = _prepare_feature_frame(frame)
    production_fit_seasons = seasons

    # Which inputs to use is decided on the validation seasons only (never the holdout).
    numeric_used, feature_choice = choose_numeric_features(prepared, validation_seasons, usable_extra_features(frame))
    features = numeric_used + CATEGORICAL_FEATURES
    if FORBIDDEN_FEATURES.intersection(features):
        raise RuntimeError("Leakage guard: a forbidden post-race field is in the chosen features")

    validation_summary: dict[str, dict[str, dict[str, Any]]] = {
        target: {} for target in TARGETS
    }
    for target in TARGETS:
        for kind in MODEL_KINDS:
            fold_metrics: list[dict[str, Any]] = []
            for validation_season in validation_seasons:
                fold_train = prepared[prepared["season"] < validation_season]
                fold_valid = prepared[prepared["season"] == validation_season]
                if fold_train.empty or fold_valid.empty:
                    continue
                y_valid = _checked_binary_values(fold_valid, target)
                model = _fit(_make_pipeline(kind, numeric_used), fold_train, features, target, validation_season - 1)
                probability = adjust_per_race(fold_valid, model.predict_proba(fold_valid[features])[:, 1], target)
                fold_metrics.append({
                    "season": int(validation_season),
                    "rows": int(len(y_valid)),
                    "positive_count": int(y_valid.sum()),
                    "metrics": _safe_metrics(y_valid, probability),
                })
            if not fold_metrics:
                raise ValueError(f"No usable rolling validation folds for {target}/{kind}")
            validation_summary[target][kind] = _aggregate_fold_metrics(fold_metrics)

    selected_models = {
        target: _select_model(validation_summary[target]) for target in TARGETS
    }

    holdout_train = prepared[prepared["season"] < holdout_season]
    holdout = prepared[prepared["season"] == holdout_season]
    final_holdout_summary: dict[str, dict[str, dict[str, Any]]] = {
        target: {} for target in TARGETS
    }
    for target in TARGETS:
        for kind in MODEL_KINDS:
            model = _fit(_make_pipeline(kind, numeric_used), holdout_train, features, target, holdout_season - 1)
            final_holdout_summary[target][kind] = _score(model, holdout, features, target)

    output: dict[str, Any] = {
        "dataset_rows": int(len(frame)),
        "seasons": seasons,
        "features_used": features,
        "training_options": {
            "feature_choice": feature_choice,
            "recency_decay": RECENCY_DECAY,
            "probabilities": PROBABILITY_ADJUSTMENT,
            "note": "Scores are computed after chances are adjusted to add up to 1 (win) or 3 (podium) within each race, exactly as predictions are made.",
        },
        "features_excluded_for_leakage": sorted(FORBIDDEN_FEATURES.intersection(frame.columns)),
        "validation": {
            "validation_seasons": [int(s) for s in validation_seasons],
            "model_summary": validation_summary,
            "selection_metric": "lowest mean Brier score, then lowest mean log loss",
        },
        "final_holdout": {
            "season": int(holdout_season),
            "training_seasons": [int(s) for s in pre_holdout_seasons],
            "model_summary": final_holdout_summary,
            "note": "This holdout is evaluated after model selection and is not used to select models.",
        },
        "selected_models": selected_models,
        "production_fit_seasons": [int(s) for s in production_fit_seasons],
        "note": (
            "Model selection uses rolling seasons before the final holdout. The 2025 holdout "
            "uses only earlier seasons. Production artifacts are refit on all available seasons "
            "only after validation and holdout evaluation are complete."
        ),
    }

    model_root = Path(model_dir)
    report = Path(report_path)
    model_root.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)

    # Fit and serialize every artifact into a staging directory first. Nothing at the
    # destination paths changes if any fit or serialization fails.
    with tempfile.TemporaryDirectory(prefix="f1_model_stage_", dir=str(model_root.parent)) as temp_name:
        temp_root = Path(temp_name)
        staged_models_root = temp_root / "models"
        staged_candidates_root = staged_models_root / "candidates"
        staged_candidates_root.mkdir(parents=True, exist_ok=True)
        staged_to_destination: dict[Path, Path] = {}

        for target in TARGETS:
            for kind in MODEL_KINDS:
                production_model = _fit(_make_pipeline(kind, numeric_used), prepared, features, target, int(max(seasons)))
                artifact_payload = {
                    "pipeline": production_model,
                    "features": features,
                    "probability_adjustment": PROBABILITY_ADJUSTMENT,
                    "recency_decay": RECENCY_DECAY,
                    "target": target,
                    "trained_through_season": int(max(seasons)),
                    "model_kind": kind,
                    "prediction_checkpoint": "post_qualifying_pre_race",
                }
                candidate_stage_path = staged_candidates_root / f"{target}_{kind}.joblib"
                joblib.dump(artifact_payload, candidate_stage_path)
                staged_to_destination[candidate_stage_path] = (
                    model_root / "candidates" / f"{target}_{kind}.joblib"
                )

                # Selected artifacts use the production fit of the model chosen only
                # from pre-holdout rolling validation.
                if selected_models[target] == kind:
                    selected_stage_path = staged_models_root / f"{target}_selected.joblib"
                    joblib.dump(artifact_payload, selected_stage_path)
                    staged_to_destination[selected_stage_path] = model_root / f"{target}_selected.joblib"

        staged_report = temp_root / "model_evaluation.json"
        staged_report.write_text(json.dumps(output, indent=2), encoding="utf-8")
        staged_to_destination[staged_report] = report

        backup_dir = temp_root / "backups"
        _commit_staged_files(staged_to_destination, backup_dir)

    return output
