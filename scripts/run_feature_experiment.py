"""Do the new features and fixes actually help? Test them the way the project always tests.

Each season is scored by a model trained only on EARLIER seasons (rolling validation over the
three seasons before the holdout, then the holdout season itself). Lower Brier score and log loss
are better. Nothing here changes production models: it only writes reports/feature_experiment.json.

    python scripts/run_feature_experiment.py
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.features.build_dataset import build_race_training_table
from src.features.extra_features import TEAM_PACE_FEATURES, usable_extra_features
from src.models.probabilities import normalize_podium, normalize_win
from src.models.train_baselines import CATEGORICAL_FEATURES, NUMERIC_FEATURES, _make_pipeline, _prepare_feature_frame, _safe_metrics

KINDS = ["logistic_regression", "random_forest", "gradient_boosting", "hist_gradient_boosting"]
TARGETS = ["target_win", "target_podium"]
HOLDOUT = 2025


def normalize(frame: pd.DataFrame, prob: np.ndarray, target: str) -> np.ndarray:
    out = prob.copy()
    fn = normalize_win if target == "target_win" else normalize_podium
    for _, idx in frame.groupby(["season", "round"]).indices.items():
        out[idx] = fn(prob[idx])
    return out


def weights(frame: pd.DataFrame, decay: float | None) -> np.ndarray | None:
    if decay is None:
        return None
    return decay ** (frame["season"].max() - frame["season"]).to_numpy(dtype=float)


def evaluate(prepared: pd.DataFrame, numeric: list[str], validation: list[int], decay: float | None, norm: bool) -> dict:
    features = numeric + CATEGORICAL_FEATURES
    result: dict = {}
    for target in TARGETS:
        for kind in KINDS:
            folds = []
            for season in [*validation, HOLDOUT]:
                train, test = prepared[prepared["season"] < season], prepared[prepared["season"] == season]
                model = _make_pipeline(kind, numeric)
                w = weights(train, decay)
                fit_kwargs = {"model__sample_weight": w} if w is not None else {}
                model.fit(train[features], train[target].astype(int), **fit_kwargs)
                prob = model.predict_proba(test[features])[:, 1]
                if norm:
                    prob = normalize(test, prob, target)
                m = _safe_metrics(test[target].astype(int).to_numpy(), prob)
                folds.append({"season": int(season), "brier": m["brier_score"], "log_loss": m["log_loss"]})
            val = [f for f in folds if f["season"] != HOLDOUT]
            hold = [f for f in folds if f["season"] == HOLDOUT][0]
            result[f"{target}/{kind}"] = {
                "validation_brier": float(np.mean([f["brier"] for f in val])), "validation_log_loss": float(np.mean([f["log_loss"] for f in val])),
                "holdout_brier": hold["brier"], "holdout_log_loss": hold["log_loss"],
            }
    return result


def summarize(res: dict) -> dict:
    out = {}
    for target in TARGETS:
        rows = [v for k, v in res.items() if k.startswith(target)]
        out[target] = {key: float(np.mean([r[key] for r in rows])) for key in ("validation_brier", "validation_log_loss", "holdout_brier", "holdout_log_loss")}
    return out


def main() -> None:
    warnings.filterwarnings("ignore")
    frame = build_race_training_table(PROJECT_ROOT / "data" / "processed").replace([np.inf, -np.inf], np.nan)
    frame["season"] = frame["season"].astype(int)
    seasons = sorted(int(s) for s in frame["season"].unique())
    validation = [s for s in seasons if s < HOLDOUT][-3:]
    extras_ok = usable_extra_features(frame)
    print(f"Validation seasons {validation}, holdout {HOLDOUT}. Extra features with enough data: {extras_ok or 'none'}")
    sets = {"current features": NUMERIC_FEATURES, "plus team pace": NUMERIC_FEATURES + TEAM_PACE_FEATURES}
    if "quali_gap_pct" in extras_ok:
        sets["plus team pace and qualifying gaps"] = NUMERIC_FEATURES + [f for f in extras_ok]
    report = {"run_at_utc": datetime.now(timezone.utc).isoformat(), "validation_seasons": validation, "holdout_season": HOLDOUT,
              "models_averaged": KINDS, "extra_features_with_enough_data": extras_ok, "experiments": []}

    def run(name: str, numeric: list[str], decay: float | None, norm: bool) -> dict:
        prepared = _prepare_feature_frame(frame)
        detail = evaluate(prepared, numeric, validation, decay, norm)
        summary = summarize(detail)
        entry = {"name": name, "features": numeric, "recency_decay": decay, "normalized_per_race": norm, "average_over_models": summary,
                 "gradient_boosting_only": {t: detail[f"{t}/gradient_boosting"] for t in TARGETS}}
        report["experiments"].append(entry)
        w, p = summary["target_win"], summary["target_podium"]
        g = entry["gradient_boosting_only"]
        print(f"   gradient boosting alone (the production model): win {g['target_win']['validation_brier']:.4f}/{g['target_win']['holdout_brier']:.4f}  podium {g['target_podium']['validation_brier']:.4f}/{g['target_podium']['holdout_brier']:.4f}")
        print(f"{name:55s} win brier {w['validation_brier']:.4f}/{w['holdout_brier']:.4f}  podium brier {p['validation_brier']:.4f}/{p['holdout_brier']:.4f}   (validation/holdout)")
        return entry

    for label, numeric in sets.items():
        run(label, numeric, None, False)
    best = min(report["experiments"], key=lambda e: e["average_over_models"]["target_win"]["validation_brier"] + e["average_over_models"]["target_podium"]["validation_brier"])
    print(f"-> best feature set by validation: {best['name']}")
    run(f"{best['name']} + chances adjusted to sum per race", best["features"], None, True)
    for decay in (0.8, 0.6):
        run(f"{best['name']} + recent seasons weighted ({decay})", best["features"], decay, False)
    for decay in (0.8, 0.6, 0.45, 0.3):
        run(f"{best['name']} + adjusted per race + recent weighted ({decay})", best["features"], decay, True)
    out = PROJECT_ROOT / "reports" / "feature_experiment.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {out.name}")


if __name__ == "__main__":
    main()
