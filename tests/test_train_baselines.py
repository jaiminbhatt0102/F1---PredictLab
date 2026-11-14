import numpy as np
import pandas as pd

from src.models.train_baselines import FEATURES, FORBIDDEN_FEATURES, _make_pipeline, _safe_metrics


def test_model_feature_whitelist_excludes_post_race_leakage():
    assert not (set(FEATURES) & FORBIDDEN_FEATURES)
    assert "finish_position" not in FEATURES
    assert "race_points" not in FEATURES
    assert "target_win" not in FEATURES


def test_pipeline_predicts_probabilities_with_unseen_categories():
    frame = pd.DataFrame({
        "season": [2018, 2019, 2020, 2021, 2022, 2023],
        "round": [1, 1, 1, 1, 1, 1],
        "grid": [1, 2, 3, 4, 5, 6],
        "qualifying_position": [1, 2, 3, 4, 5, 6],
        "sprint_position": [np.nan, 2, np.nan, 4, np.nan, 1],
        "sprint_points": [np.nan, 7, np.nan, 3, np.nan, 8],
        "driver_prior_mean_finish_3": [np.nan, 3, 4, 5, 6, 7],
        "driver_prior_mean_points_3": [np.nan, 10, 8, 6, 4, 2],
        "driver_prior_race_count": [0, 1, 2, 3, 4, 5],
        "driver_id": ["a", "b", "c", "a", "b", "c"],
        "constructor_id": ["x", "y", "z", "x", "y", "z"],
        "circuit_id": ["one"] * 6,
    })
    y = np.array([1, 0, 0, 1, 0, 0])
    model = _make_pipeline("logistic_regression")
    model.fit(frame, y)
    test = frame.iloc[:2].copy()
    test.loc[test.index[0], "driver_id"] = "unseen_driver"
    probabilities = model.predict_proba(test)[:, 1]
    assert probabilities.shape == (2,)
    assert np.all((probabilities >= 0) & (probabilities <= 1))


def test_metrics_include_calibration_metrics():
    result = _safe_metrics(np.array([0, 1, 0, 1]), np.array([0.1, 0.8, 0.2, 0.7]))
    assert 0 <= result["brier_score"] <= 1
    assert result["log_loss"] >= 0
    assert result["roc_auc"] == 1.0


from pathlib import Path

import pytest

import src.models.train_baselines as training
from src.models.train_baselines import _checked_target


class _PriorOnlyTestModel:
    """Fast deterministic test double for the training workflow."""

    def fit(self, X, y):
        self.probability_ = float(np.mean(y))
        return self

    def predict_proba(self, X):
        p = np.full(len(X), self.probability_)
        return np.column_stack([1.0 - p, p])


def test_checked_target_rejects_missing_and_invalid_labels():
    with pytest.raises(ValueError, match="missing or invalid"):
        _checked_target(pd.DataFrame({"target_win": [1, np.nan]}), "target_win")

    with pytest.raises(ValueError, match="binary labels"):
        _checked_target(pd.DataFrame({"target_win": [0, 2]}), "target_win")


def test_checked_target_rejects_single_class():
    with pytest.raises(ValueError, match="only one class"):
        _checked_target(pd.DataFrame({"target_win": [0, 0, 0]}), "target_win")


def test_rolling_selection_excludes_2025_and_keeps_2026_for_production(
    tmp_path, monkeypatch
):
    # This test checks workflow logic, not real model performance.
    monkeypatch.setattr(
        training,
        "_make_pipeline",
        lambda kind, numeric_features=None: _PriorOnlyTestModel(),
    )

    rows = []
    for season in range(2018, 2027):
        for round_no in range(1, 5):
            rows.append({
                "season": season,
                "round": round_no,
                "grid": round_no,
                "qualifying_position": round_no,
                "sprint_position": np.nan,
                "sprint_points": np.nan,
                "driver_prior_mean_finish_3": float(round_no),
                "driver_prior_mean_points_3": float(round_no),
                "driver_prior_race_count": round_no,
                "driver_id": f"driver_{round_no}",
                "constructor_id": f"team_{round_no % 2}",
                "circuit_id": f"circuit_{round_no}",
                "target_win": int(round_no == 1),
                "target_podium": int(round_no <= 2),
            })

    dataset_path = tmp_path / "training.csv"
    pd.DataFrame(rows).to_csv(dataset_path, index=False)

    model_dir = tmp_path / "models"
    report_path = tmp_path / "reports" / "evaluation.json"

    report = training.train_and_evaluate(
        dataset_path=dataset_path,
        model_dir=model_dir,
        report_path=report_path,
    )

    expected_models = {
        "prior_baseline",
        "logistic_regression",
        "random_forest",
        "extra_trees",
        "gradient_boosting",
        "hist_gradient_boosting",
    }

    assert set(report["validation"]["model_summary"]["target_win"]) == expected_models
    assert set(report["validation"]["model_summary"]["target_podium"]) == expected_models

    assert report["final_holdout"]["season"] == 2025
    assert report["final_holdout"]["training_seasons"] == list(range(2018, 2025))
    assert report["validation"]["validation_seasons"] == [2022, 2023, 2024]
    assert 2025 not in report["validation"]["validation_seasons"]
    assert 2026 not in report["validation"]["validation_seasons"]

    assert report["production_fit_seasons"] == list(range(2018, 2027))
    assert report["selected_models"]["target_win"] in expected_models
    assert report["selected_models"]["target_podium"] in expected_models

    assert (model_dir / "target_win_selected.joblib").exists()
    assert (model_dir / "target_podium_selected.joblib").exists()
    assert report_path.exists()

    for target in ("target_win", "target_podium"):
        for kind in expected_models:
            assert (model_dir / "candidates" / f"{target}_{kind}.joblib").exists()


def test_training_failure_does_not_overwrite_existing_selected_artifacts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        training,
        "_make_pipeline",
        lambda kind, numeric_features=None: (_ for _ in ()).throw(RuntimeError("simulated failure")),
    )

    rows = []
    for season in range(2018, 2027):
        for round_no in range(1, 5):
            rows.append({
                "season": season,
                "round": round_no,
                "grid": round_no,
                "qualifying_position": round_no,
                "sprint_position": np.nan,
                "sprint_points": np.nan,
                "driver_prior_mean_finish_3": float(round_no),
                "driver_prior_mean_points_3": float(round_no),
                "driver_prior_race_count": round_no,
                "driver_id": f"driver_{round_no}",
                "constructor_id": f"team_{round_no % 2}",
                "circuit_id": f"circuit_{round_no}",
                "target_win": int(round_no == 1),
                "target_podium": int(round_no <= 2),
            })

    dataset_path = tmp_path / "training.csv"
    pd.DataFrame(rows).to_csv(dataset_path, index=False)

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    sentinels = {}

    for target in ("target_win", "target_podium"):
        path = model_dir / f"{target}_selected.joblib"
        path.write_bytes(b"existing-artifact")
        sentinels[path] = path.read_bytes()

    with pytest.raises(RuntimeError, match="simulated failure"):
        training.train_and_evaluate(
            dataset_path=dataset_path,
            model_dir=model_dir,
            report_path=tmp_path / "reports" / "evaluation.json",
        )

    for path, contents in sentinels.items():
        assert path.read_bytes() == contents