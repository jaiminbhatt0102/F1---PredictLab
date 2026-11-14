"""Build leakage-aware event-level race training tables from normalized results."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

from src.features.extra_features import QUALI_GAP_FEATURES, add_team_pace, qualifying_features

KEYS = ["season", "round", "driver_id"]

def _read_session(directory: Path, season: int, session: str) -> pd.DataFrame:
    path = directory / f"{season}_{session}_normalized.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)

def _merge_quali_gaps(race: pd.DataFrame, qual: pd.DataFrame) -> pd.DataFrame:
    """Add per-event qualifying time-gap features. Missing lap times stay missing (never zero)."""
    parts = []
    for (season, rnd), group in qual.groupby(["season", "round"]):
        feats = qualifying_features(group)
        feats["season"], feats["round"] = season, rnd
        parts.append(feats)
    if not parts:
        for col in QUALI_GAP_FEATURES:
            race[col] = float("nan")
        return race
    return race.merge(pd.concat(parts, ignore_index=True), on=KEYS, how="left", validate="one_to_one")


def build_race_training_table(processed_dir: str | Path = "data/processed") -> pd.DataFrame:
    """Create one row per driver/race; prior-form features span season boundaries.

    Prediction checkpoint: post-qualifying, pre-race. Current race finish/points/status
    are labels or descriptive metadata and must never be passed to model.fit as features.
    """
    base = Path(processed_dir)
    race_files = sorted(base.glob("*_race_normalized.csv"))
    race_frames: list[pd.DataFrame] = []

    for race_path in race_files:
        try:
            season = int(race_path.name.split("_")[0])
        except ValueError:
            continue
        race = pd.read_csv(race_path)
        if race.empty or not set(KEYS).issubset(race.columns):
            continue

        # Keep only a single, unambiguous qualifying position per driver/event.
        qual = _read_session(base, season, "qualifying")
        if not qual.empty and set(KEYS + ["position"]).issubset(qual.columns):
            q = qual[KEYS + ["position"]].copy()
            q["position"] = pd.to_numeric(q["position"], errors="coerce")
            q = q.rename(columns={"position": "qualifying_position"})
            # A duplicate here indicates source/normalization trouble; don't silently multiply rows.
            if q.duplicated(KEYS).any():
                raise ValueError(f"Duplicate qualifying keys in {season}_qualifying_normalized.csv")
            race = race.merge(q, on=KEYS, how="left", validate="one_to_one")
            race = _merge_quali_gaps(race, qual)
        else:
            race["qualifying_position"] = pd.NA
            for col in QUALI_GAP_FEATURES:
                race[col] = float("nan")
        # Sprint results are known before the Grand Prix only on sprint weekends.
        # Join by event and driver; absent sprint weekends remain missing and are
        # imputed by the model pipeline rather than treated as zero performance.
        sprint = _read_session(base, season, "sprint")
        if not sprint.empty and set(KEYS + ["position", "points"]).issubset(sprint.columns):
            sp = sprint[KEYS + ["position", "points"]].copy()
            sp["position"] = pd.to_numeric(sp["position"], errors="coerce")
            sp["points"] = pd.to_numeric(sp["points"], errors="coerce")
            sp = sp.rename(columns={
                "position": "sprint_position",
                "points": "sprint_points",
            })
            if sp.duplicated(KEYS).any():
                raise ValueError(f"Duplicate sprint keys in {season}_sprint_normalized.csv")
            race = race.merge(sp, on=KEYS, how="left", validate="one_to_one")
        else:
            race["sprint_position"] = pd.NA
            race["sprint_points"] = pd.NA
        race_frames.append(race)

    if not race_frames:
        return pd.DataFrame()

    dataset = pd.concat(race_frames, ignore_index=True, sort=False)
    if dataset.duplicated(KEYS).any():
        duplicates = dataset.loc[dataset.duplicated(KEYS, keep=False), KEYS].head(10)
        raise ValueError(f"Duplicate race driver/event keys detected:\n{duplicates}")

    dataset["race_position_num"] = pd.to_numeric(dataset.get("position"), errors="coerce")
    dataset["race_points_num"] = pd.to_numeric(dataset.get("points"), errors="coerce")
    dataset["race_date_sort"] = pd.to_datetime(dataset.get("race_date"), errors="coerce")
    # Date + season + round gives stable chronology, including across season boundaries.
    dataset = dataset.sort_values(
        ["race_date_sort", "season", "round", "driver_id"], na_position="last"
    ).reset_index(drop=True)

    # Shift first: the current race's result can never enter its own prior-form features.
    grouped = dataset.groupby("driver_id", sort=False)
    dataset["driver_prior_mean_finish_3"] = grouped["race_position_num"].transform(
        lambda values: values.shift(1).rolling(3, min_periods=1).mean()
    )
    dataset["driver_prior_mean_points_3"] = grouped["race_points_num"].transform(
        lambda values: values.shift(1).rolling(3, min_periods=1).mean()
    )
    dataset["driver_prior_race_count"] = grouped.cumcount()
    # Team pace: how the constructor's cars did in their previous three events (current event excluded).
    dataset = add_team_pace(dataset)

    dataset = dataset.rename(columns={
        "position": "finish_position",
        "points": "race_points",
        "status": "race_status",
    })
    dataset["prediction_checkpoint"] = "post_qualifying_pre_race"
    finish_num = pd.to_numeric(dataset["finish_position"], errors="coerce")
    dataset["target_win"] = finish_num.eq(1).astype("int64")
    dataset["target_podium"] = finish_num.between(1, 3).astype("int64")
    return dataset.sort_values(
        ["race_date_sort", "season", "round", "driver_id"], na_position="last"
    ).reset_index(drop=True)

def write_race_training_table(
    processed_dir: str | Path = "data/processed",
    output_path: str | Path = "data/features/race_training.csv",
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = build_race_training_table(processed_dir)
    frame.to_csv(output, index=False)
    return output
