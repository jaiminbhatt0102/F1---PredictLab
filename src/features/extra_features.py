"""Extra pre-race features shared by training and prediction.

Both the training table and live predictions call these same functions, so a feature can
never mean one thing when the model learns and another when it predicts.

Nothing here looks at the race being predicted:
- team pace uses only earlier races (the current event's results are shifted out);
- qualifying gaps use this weekend's qualifying, which is known before the race.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

TEAM_PACE_FEATURES = ["constructor_prior_mean_finish_3", "constructor_prior_mean_quali_3"]
QUALI_GAP_FEATURES = ["quali_gap_pct", "quali_stage_reached"]
EXTRA_FEATURES = TEAM_PACE_FEATURES + QUALI_GAP_FEATURES

_TIME = re.compile(r"^(?:(\d+):)?(\d+(?:\.\d+)?)$")


def parse_lap_time(value: object) -> float:
    """'1:23.456' or '59.123' -> seconds. Anything else -> NaN (never 0)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    match = _TIME.match(str(value).strip())
    if not match:
        return float("nan")
    minutes, seconds = match.groups()
    total = float(seconds) + 60 * int(minutes or 0)
    return total if total > 0 else float("nan")


def qualifying_features(qual: pd.DataFrame) -> pd.DataFrame:
    """Per driver, for one event: gap to pole in percent, and the last qualifying stage reached (1-3).

    A driver knocked out in Q1 only has a Q1 time, which is slower than a Q3 lap because the
    track is faster late in qualifying. `quali_stage_reached` lets the model account for that.
    """
    out = qual[["driver_id"]].copy()
    stages = np.column_stack([qual[c].map(parse_lap_time).to_numpy() if c in qual.columns else np.full(len(qual), np.nan) for c in ("q1", "q2", "q3")])
    best = np.nanmin(np.where(np.isnan(stages), np.inf, stages), axis=1)
    best[~np.isfinite(best)] = np.nan
    pole = np.nanmin(best) if np.isfinite(best).any() else np.nan
    out["quali_gap_pct"] = (best - pole) / pole * 100 if np.isfinite(pole) else np.nan
    reached = np.where(~np.isnan(stages[:, 2]), 3, np.where(~np.isnan(stages[:, 1]), 2, np.where(~np.isnan(stages[:, 0]), 1, np.nan)))
    out["quali_stage_reached"] = reached
    return out.reset_index(drop=True)


def add_team_pace(dataset: pd.DataFrame) -> pd.DataFrame:
    """Add each constructor's average finish and qualifying position over its previous three events.

    Needs columns: constructor_id, season, round, race_date_sort, race_position_num, qualifying_position.
    """
    work = dataset.copy()
    work["_finish"] = pd.to_numeric(work["race_position_num"], errors="coerce")
    work["_quali"] = pd.to_numeric(work["qualifying_position"], errors="coerce")
    events = (
        work.groupby(["constructor_id", "season", "round"], sort=False)
        .agg(_date=("race_date_sort", "first"), _finish=("_finish", "mean"), _quali=("_quali", "mean"))
        .reset_index()
        .sort_values(["constructor_id", "_date", "season", "round"])
    )
    grouped = events.groupby("constructor_id", sort=False)
    # shift(1): an event's own result never enters its own team-pace figure.
    events["constructor_prior_mean_finish_3"] = grouped["_finish"].transform(lambda v: v.shift(1).rolling(3, min_periods=1).mean())
    events["constructor_prior_mean_quali_3"] = grouped["_quali"].transform(lambda v: v.shift(1).rolling(3, min_periods=1).mean())
    keep = ["constructor_id", "season", "round", *TEAM_PACE_FEATURES]
    base = work.drop(columns=[c for c in TEAM_PACE_FEATURES if c in work.columns] + ["_finish", "_quali"])
    return base.merge(events[keep], on=["constructor_id", "season", "round"], how="left", validate="many_to_one")


def team_pace_for_event(training: pd.DataFrame, event: pd.DataFrame) -> pd.DataFrame:
    """Team-pace features for an upcoming event, computed exactly as in training.

    `event` needs constructor_id, season, round. Only strictly earlier events from `training` are used.
    """
    season, round_no = int(event["season"].iloc[0]), int(event["round"].iloc[0])
    hist = training[(training["season"] < season) | ((training["season"] == season) & (training["round"] < round_no))]
    cols = ["constructor_id", "season", "round", "race_date_sort", "race_position_num", "qualifying_position"]
    hist = hist[cols].copy()
    hist["race_date_sort"] = pd.to_datetime(hist["race_date_sort"], errors="coerce")
    after = (hist["race_date_sort"].max() if len(hist) else pd.Timestamp("1970-01-01")) + pd.Timedelta(days=1)
    stub = event[["constructor_id", "season", "round"]].drop_duplicates().copy()
    stub["race_date_sort"], stub["race_position_num"], stub["qualifying_position"] = after, np.nan, np.nan
    combined = add_team_pace(pd.concat([hist, stub], ignore_index=True))
    got = combined[(combined["season"] == season) & (combined["round"] == round_no)]
    return got[["constructor_id", *TEAM_PACE_FEATURES]].drop_duplicates("constructor_id")


def usable_extra_features(frame: pd.DataFrame, min_coverage: float = 0.5, min_seasons: int = 3) -> list[str]:
    """Extras that are actually present in enough rows and seasons to train on."""
    usable = []
    for col in EXTRA_FEATURES:
        if col not in frame.columns:
            continue
        filled = frame[col].notna()
        by_season = filled.groupby(frame["season"]).mean()
        if filled.mean() >= min_coverage and int((by_season >= min_coverage).sum()) >= min_seasons:
            usable.append(col)
    return usable


def add_event_extras(event: pd.DataFrame, training: pd.DataFrame | None) -> pd.DataFrame:
    """Add team-pace and qualifying-gap columns to one upcoming event's rows (one row per driver).

    Columns the data cannot support (no lap times yet, no history file) are left missing, never zero.
    """
    out = event.drop(columns=[c for c in EXTRA_FEATURES if c in event.columns]).copy()
    out = out.merge(qualifying_features(event), on="driver_id", how="left")
    needed = {"constructor_id", "season", "round", "race_date_sort", "race_position_num", "qualifying_position"}
    if training is not None and needed <= set(training.columns) and len(out):
        pace = team_pace_for_event(training, out[["constructor_id", "season", "round"]])
        out = out.merge(pace, on="constructor_id", how="left")
    for col in TEAM_PACE_FEATURES:
        if col not in out.columns:
            out[col] = np.nan
    return out
