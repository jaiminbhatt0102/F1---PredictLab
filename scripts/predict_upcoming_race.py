
"""Predict an upcoming Grand Prix using completed session data.

This is an offline/local inference script. It does not scrape or schedule itself.
Run after collecting and normalizing the current season's completed sessions.

Predictions use the existing selected win and podium model artifacts.
Qualifying position is only a provisional grid proxy when official grid data
is unavailable. This does not guarantee that the model was trained on the same
grid definition; that training/inference contract must be validated separately.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from collections.abc import Mapping

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.extra_features import EXTRA_FEATURES, add_event_extras  # noqa: E402
from src.models.probabilities import normalize_podium, normalize_win  # noqa: E402

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

IDENTITY_COLUMNS = ["season", "round", "driver_id"]
HISTORY_POSITION_COLUMNS = ("race_position_num", "position")
HISTORY_POINTS_COLUMNS = ("race_points_num", "points")


def resolve_path(value: str | Path) -> Path:
    """Resolve relative paths against the repository root, not the shell CWD."""
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def require_columns(
    frame: pd.DataFrame,
    required: list[str],
    description: str,
) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{description} is missing required columns: {missing}")


def _load_training_for_extras(history_path: Path) -> pd.DataFrame | None:
    """The training table, used to compute team-pace features the same way training did."""
    try:
        frame = pd.read_csv(history_path)
    except (OSError, ValueError):
        return None
    frame["race_date_sort"] = pd.to_datetime(frame.get("race_date_sort"), errors="coerce")
    return frame


def first_available_column(
    frame: pd.DataFrame,
    candidates: tuple[str, ...],
    description: str,
    required: bool = True,
) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    if required:
        raise ValueError(
            f"{description} must contain one of these columns: {list(candidates)}"
        )
    return None


def load_history(history_path: Path, season: int, round_no: int) -> pd.DataFrame:
    """Load only valid prior race classifications for historical form."""
    if not history_path.exists():
        raise FileNotFoundError(
            f"Race history not found: {history_path}. "
            "Build the race training dataset first."
        )

    history = pd.read_csv(history_path)
    require_columns(
        history,
        ["season", "round", "driver_id"],
        "Race history",
    )

    position_column = first_available_column(
        history, HISTORY_POSITION_COLUMNS, "Race history finishing position"
    )
    points_column = first_available_column(
        history, HISTORY_POINTS_COLUMNS, "Race history points", required=False
    )

    history["season"] = pd.to_numeric(history["season"], errors="coerce")
    history["round"] = pd.to_numeric(history["round"], errors="coerce")
    history["driver_id"] = history["driver_id"].astype("string").str.strip()
    history["_position"] = pd.to_numeric(
        history[position_column], errors="coerce"
    )
    history["_points"] = (
        pd.to_numeric(history[points_column], errors="coerce")
        if points_column
        else np.nan
    )

    # Only classified finishes with valid event identity count as prior starts.
    # Non-finishers and missing classifications are not silently treated as
    # completed results or as ordinary negative target labels.
    history = history[
        history["season"].notna()
        & history["round"].notna()
        & history["driver_id"].notna()
        & history["driver_id"].ne("")
        & history["_position"].notna()
        & history["_position"].gt(0)
    ].copy()

    # Strict temporal cutoff: the event being predicted cannot enter its own
    # historical features, even if it already appears in the history CSV.
    history = history[
        (history["season"] < season)
        | (
            (history["season"] == season)
            & (history["round"] < round_no)
        )
    ].copy()

    date_column = (
        "race_date_sort"
        if "race_date_sort" in history.columns
        else "race_date"
        if "race_date" in history.columns
        else None
    )

    if date_column:
        history["_sort_date"] = pd.to_datetime(
            history[date_column], errors="coerce", utc=True
        )
        history = history.sort_values(
            ["season", "round", "_sort_date"],
            kind="stable",
            na_position="first",
        )
    else:
        history = history.sort_values(
            ["season", "round"], kind="stable"
        )

    return history


def add_driver_history_features(
    event: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    """Compute recent form and total prior classified starts per driver."""
    event = event.copy()
    event["driver_prior_mean_finish_3"] = np.nan
    event["driver_prior_mean_points_3"] = np.nan
    event["driver_prior_race_count"] = 0

    history_by_driver = {
        str(driver_id): group
        for driver_id, group in history.groupby("driver_id", sort=False)
    }

    for index, row in event.iterrows():
        driver_id = str(row["driver_id"])
        past = history_by_driver.get(driver_id)

        if past is None or past.empty:
            continue

        recent = past.tail(3)
        event.loc[index, "driver_prior_mean_finish_3"] = recent[
            "_position"
        ].mean()

        recent_points = recent["_points"].dropna()
        if not recent_points.empty:
            event.loc[index, "driver_prior_mean_points_3"] = (
                recent_points.mean()
            )

        event.loc[index, "driver_prior_race_count"] = len(past)

    return event


def build_upcoming_rows(
    season: int,
    round_no: int,
    processed_dir: Path,
    history_path: Path,
) -> pd.DataFrame:
    if season < 1950 or round_no < 1:
        raise ValueError("Provide a valid F1 season and a round number >= 1.")

    qual_path = processed_dir / f"{season}_qualifying_normalized.csv"
    if not qual_path.exists():
        raise FileNotFoundError(
            f"Missing {qual_path}. Collect and normalize this season first."
        )

    qualifying = pd.read_csv(qual_path)
    require_columns(
        qualifying,
        ["season", "round", "driver_id", "constructor_id",
         "circuit_id", "position"],
        "Normalized qualifying data",
    )

    qualifying["season"] = pd.to_numeric(
        qualifying["season"], errors="coerce"
    )
    qualifying["round"] = pd.to_numeric(
        qualifying["round"], errors="coerce"
    )

    event = qualifying[
        (qualifying["season"] == season)
        & (qualifying["round"] == round_no)
    ].copy()

    if event.empty:
        raise ValueError(
            f"No qualifying rows found for season={season}, "
            f"round={round_no} in {qual_path}"
        )

    if event["driver_id"].isna().any() or event["driver_id"].astype(
        str
    ).str.strip().eq("").any():
        raise ValueError("Qualifying data contains missing driver IDs.")

    if event.duplicated(["season", "round", "driver_id"]).any():
        raise ValueError("Duplicate qualifying driver/event rows found.")

    event["qualifying_position"] = pd.to_numeric(
        event["position"], errors="coerce"
    )
    if event["qualifying_position"].isna().any():
        raise ValueError(
            "Qualifying position is missing or invalid for one or more drivers."
        )

    # Do not pretend qualifying order is the official starting grid.
    grid_is_proxy = "grid" not in event.columns
    if grid_is_proxy:
        event["grid"] = event["qualifying_position"]
    else:
        event["grid"] = pd.to_numeric(event["grid"], errors="coerce")
        missing_grid = event["grid"].isna()
        event.loc[missing_grid, "grid"] = event.loc[
            missing_grid, "qualifying_position"
        ]
        grid_is_proxy = bool(missing_grid.any())

    event["sprint_position"] = np.nan
    event["sprint_points"] = np.nan

    sprint_path = processed_dir / f"{season}_sprint_normalized.csv"
    if sprint_path.exists():
        sprint = pd.read_csv(sprint_path)

        if not sprint.empty:
            require_columns(
                sprint,
                ["season", "round", "driver_id", "position", "points"],
                "Normalized sprint data",
            )
            sprint["season"] = pd.to_numeric(
                sprint["season"], errors="coerce"
            )
            sprint["round"] = pd.to_numeric(
                sprint["round"], errors="coerce"
            )
            sprint = sprint[
                (sprint["season"] == season)
                & (sprint["round"] == round_no)
            ].copy()

            if sprint.duplicated(["season", "round", "driver_id"]).any():
                raise ValueError("Duplicate sprint driver/event rows found.")

            sprint = sprint[
                ["season", "round", "driver_id", "position", "points"]
            ].rename(
                columns={
                    "position": "sprint_position",
                    "points": "sprint_points",
                }
            )

            event = event.drop(
                columns=["sprint_position", "sprint_points"],
                errors="ignore",
            )
            event = event.merge(
                sprint,
                on=["season", "round", "driver_id"],
                how="left",
                validate="one_to_one",
            )

    history = load_history(history_path, season, round_no)
    event = add_driver_history_features(event, history)

    event["season"] = season
    event["round"] = round_no
    event = add_event_extras(event, _load_training_for_extras(history_path))

    for column in CATEGORICAL_FEATURES:
        event[column] = (
            event[column].astype("string").fillna("unknown").astype(str)
        )
        event.loc[event[column].str.strip().eq(""), column] = "unknown"

    for column in NUMERIC_FEATURES + [c for c in EXTRA_FEATURES if c in event.columns]:
        event[column] = pd.to_numeric(event[column], errors="coerce")

    event.attrs["grid_is_proxy"] = grid_is_proxy
    return event


def load_prediction_artifact(
    path: Path,
    target: str,
) -> tuple[object, list[str], str]:
    if not path.exists():
        raise FileNotFoundError(
            f"Selected model artifact not found: {path}. "
            "Run the validated training workflow first."
        )

    try:
        artifact = joblib.load(path)
    except Exception as exc:
        raise ValueError(
            f"Could not load model artifact {path}: {exc}"
        ) from exc

    if not isinstance(artifact, Mapping):
        raise ValueError(f"Model artifact {path} must be a dictionary-like object.")

    if artifact.get("target") != target:
        raise ValueError(
            f"Artifact {path} is for target={artifact.get('target')!r}, "
            f"but {target!r} was requested."
        )

    pipeline = artifact.get("pipeline")
    if pipeline is None or not callable(
        getattr(pipeline, "predict_proba", None)
    ):
        raise ValueError(
            f"Artifact {path} has no usable pipeline.predict_proba method."
        )

    features = artifact.get("features", FEATURES)
    if (
        not isinstance(features, (list, tuple))
        or not features
        or not all(isinstance(feature, str) for feature in features)
        or len(features) != len(set(features))
    ):
        raise ValueError(
            f"Artifact {path} has an invalid or duplicate feature list."
        )

    model_kind = str(artifact.get("model_kind", "unknown"))
    return pipeline, list(features), model_kind


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate local win and podium estimates for a Grand Prix."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", dest="round_no", type=int, required=True)
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument("--history", default="data/features/race_training.csv")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--output", default="reports/upcoming_race_predictions.csv")
    args = parser.parse_args()

    processed_dir = resolve_path(args.processed_dir)
    history_path = resolve_path(args.history)
    model_dir = resolve_path(args.model_dir)
    output_path = resolve_path(args.output)

    event = build_upcoming_rows(
        args.season, args.round_no, processed_dir, history_path
    )

    output_columns = [
        "season", "round", "race_name", "race_date", "driver_id",
        "driver_code", "driver_given_name", "driver_family_name",
        "constructor_name", "grid", "qualifying_position",
        "sprint_position", "sprint_points",
    ]
    outputs = event[
        [column for column in output_columns if column in event.columns]
    ].copy()

    for target in ("target_win", "target_podium"):
        artifact_path = model_dir / f"{target}_selected.joblib"
        pipeline, features, model_kind = load_prediction_artifact(
            artifact_path, target
        )

        missing = [column for column in features if column not in event.columns]
        if missing:
            raise ValueError(
                f"{target} model requires missing features {missing}. "
                "Training and inference schemas must match."
            )

        model_input = event[features]
        probabilities = np.asarray(
            pipeline.predict_proba(model_input)
        )

        if (
            probabilities.ndim != 2
            or probabilities.shape[0] != len(event)
            or probabilities.shape[1] < 2
        ):
            raise ValueError(
                f"{target} model returned an invalid probability array "
                f"with shape {probabilities.shape}."
            )

        probabilities = probabilities[:, 1]
        if (
            not np.isfinite(probabilities).all()
            or ((probabilities < 0) | (probabilities > 1)).any()
        ):
            raise ValueError(
                f"{target} model returned non-finite or out-of-range probabilities."
            )

        # One winner and three podium places per race: make the field's chances add up to that.
        probabilities = (
            normalize_win(probabilities) if target == "target_win" else normalize_podium(probabilities)
        )
        outputs[f"{target}_probability"] = probabilities
        outputs[f"{target}_rank"] = (
            outputs[f"{target}_probability"]
            .rank(method="min", ascending=False)
            .astype(int)
        )
        outputs[f"{target}_model"] = model_kind

    outputs = outputs.sort_values(
        "target_win_probability", ascending=False
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    outputs.to_csv(output_path, index=False)

    print(f"Predictions written to: {output_path}")
    print(outputs.to_string(index=False))

    if event.attrs.get("grid_is_proxy", False):
        print(
            "\nWARNING: At least one grid value uses qualifying position as "
            "a proxy. Official grid penalties may change the starting order."
        )

    print(
        "\nThese probabilities are model estimates, not guarantees. "
        "Verify that the selected artifacts were trained for the same "
        "feature contract used at inference."
    )


if __name__ == "__main__":
    main()
