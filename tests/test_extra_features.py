import numpy as np
import pandas as pd

from src.data.collectors import _race_table
from src.features.build_dataset import build_race_training_table
from src.features.extra_features import (
    add_team_pace, parse_lap_time, qualifying_features, team_pace_for_event, usable_extra_features,
)


def test_lap_time_parsing():
    assert parse_lap_time("1:23.456") == 83.456
    assert parse_lap_time("59.5") == 59.5
    for bad in (None, "", "NaN", "abc", float("nan"), "0"):
        assert np.isnan(parse_lap_time(bad))


def test_quali_gap_and_stage():
    q = pd.DataFrame({"driver_id": ["a", "b", "c", "d"], "q1": ["1:21.0", "1:21.5", "1:22.0", None], "q2": ["1:20.5", "1:21.0", None, None], "q3": ["1:20.0", None, None, None]})
    f = qualifying_features(q).set_index("driver_id")
    assert f.loc["a", "quali_gap_pct"] == 0 and f.loc["a", "quali_stage_reached"] == 3
    assert round(f.loc["b", "quali_gap_pct"], 3) == round((81.0 - 80.0) / 80.0 * 100, 3) and f.loc["b", "quali_stage_reached"] == 2
    assert f.loc["c", "quali_stage_reached"] == 1
    assert np.isnan(f.loc["d", "quali_gap_pct"]) and np.isnan(f.loc["d", "quali_stage_reached"])   # missing stays missing, never 0


def test_quali_gap_is_missing_without_times():
    q = pd.DataFrame({"driver_id": ["a", "b"], "q1": [None, None], "q2": [None, None], "q3": [None, None]})
    assert qualifying_features(q)["quali_gap_pct"].isna().all()


def _table():
    rows = []
    for rnd in range(1, 6):
        for team, drivers in (("fast", ("f1", "f2")), ("slow", ("s1", "s2"))):
            for d in drivers:
                rows.append({"constructor_id": team, "season": 2026, "round": rnd, "driver_id": d, "race_date_sort": pd.Timestamp("2026-03-01") + pd.Timedelta(days=14 * rnd),
                             "race_position_num": (1 if team == "fast" else 15) + rnd, "qualifying_position": 2 if team == "fast" else 16})
    return pd.DataFrame(rows)


def test_team_pace_never_sees_the_current_event():
    base = add_team_pace(_table())
    changed = _table()
    changed.loc[changed["round"] == 5, "race_position_num"] = 99      # wreck the latest result
    after = add_team_pace(changed)
    r5 = lambda d: d[(d["round"] == 5) & (d["constructor_id"] == "fast")]["constructor_prior_mean_finish_3"].iloc[0]
    assert r5(base) == r5(after)                                      # round 5's own result does not affect round 5
    assert add_team_pace(changed)[lambda d: (d["round"] == 6)].empty  # sanity: no invented rounds
    first = base[(base["round"] == 1)]["constructor_prior_mean_finish_3"]
    assert first.isna().all()                                         # nothing before round 1


def test_team_pace_uses_three_previous_events():
    out = add_team_pace(_table())
    row = out[(out["round"] == 5) & (out["constructor_id"] == "fast")].iloc[0]
    assert row["constructor_prior_mean_finish_3"] == np.mean([2 + 1, 3 + 1, 4 + 1]) and row["constructor_prior_mean_quali_3"] == 2


def test_prediction_time_matches_training_time():
    """The same numbers must come out whether a race is in the training table or is being predicted."""
    full = build_race_training_table("data/processed")
    event = full[(full["season"] == 2026) & (full["round"] == 17)][["constructor_id", "season", "round"]]
    got = team_pace_for_event(full, event).set_index("constructor_id")
    trained = full[(full["season"] == 2026) & (full["round"] == 17)].drop_duplicates("constructor_id").set_index("constructor_id")
    for col in ("constructor_prior_mean_finish_3", "constructor_prior_mean_quali_3"):
        pd.testing.assert_series_equal(got[col].sort_index(), trained[col].sort_index(), check_names=False, atol=1e-9)


def test_unusable_features_are_not_offered():
    frame = pd.DataFrame({"season": [2024] * 10 + [2025] * 10, "quali_gap_pct": [np.nan] * 20, "quali_stage_reached": [np.nan] * 20,
                          "constructor_prior_mean_finish_3": list(range(20)), "constructor_prior_mean_quali_3": list(range(20))})
    assert usable_extra_features(frame) == []                         # only 2 seasons, and times missing


def test_enough_data_makes_features_usable():
    frame = pd.DataFrame({"season": [2022] * 5 + [2023] * 5 + [2024] * 5, "quali_gap_pct": [0.5] * 15, "quali_stage_reached": [3] * 15,
                          "constructor_prior_mean_finish_3": [3.0] * 15, "constructor_prior_mean_quali_3": [3.0] * 15})
    assert set(usable_extra_features(frame)) == {"quali_gap_pct", "quali_stage_reached", "constructor_prior_mean_finish_3", "constructor_prior_mean_quali_3"}


def test_collector_keeps_qualifying_times():
    payload = {"MRData": {"RaceTable": {"Races": [{"season": "2026", "round": "1", "raceName": "X", "date": "2026-03-01", "Circuit": {"circuitId": "c", "circuitName": "C"},
               "QualifyingResults": [{"position": "1", "Driver": {"driverId": "d"}, "Constructor": {"constructorId": "t"}, "Q1": "1:21.000", "Q2": "1:20.500", "Q3": "1:20.000"}]}]}}}
    row = _race_table(payload, "QualifyingResults")[0]
    assert (row["q1"], row["q2"], row["q3"]) == ("1:21.000", "1:20.500", "1:20.000")


# ---- probability adjustment and training options
def test_win_chances_add_up_to_one_and_podium_to_three():
    from src.models.probabilities import normalize_podium, normalize_win
    rng = np.random.default_rng(1)
    for _ in range(50):
        p = rng.uniform(0.001, 0.9, size=20)
        assert abs(normalize_win(p).sum() - 1) < 1e-9
        q = normalize_podium(p)
        assert abs(q.sum() - 3) < 1e-6 and q.max() <= 1.0 and q.min() >= 0


def test_adjustment_keeps_driver_order():
    from src.models.probabilities import normalize_podium, normalize_win
    p = np.array([0.5, 0.2, 0.1, 0.05])
    assert list(np.argsort(-normalize_win(p))) == list(np.argsort(-p))
    assert list(np.argsort(-normalize_podium(p, 2))) == list(np.argsort(-p))


def test_small_fields_and_empty_chances_are_safe():
    from src.models.probabilities import normalize_podium, normalize_win
    assert normalize_win(np.zeros(5)).sum() == 0                      # nothing invented from nothing
    assert normalize_podium(np.array([0.2, 0.3]), 3).tolist() == [1.0, 1.0]


def test_recent_seasons_count_more():
    from src.models.train_baselines import recency_weights
    w = recency_weights(pd.DataFrame({"season": [2022, 2023, 2024]}), 2024)
    assert w[2] == 1.0 and w[1] < w[2] and w[0] < w[1]


def test_training_picks_team_pace_when_it_helps_and_ignores_missing_times():
    from src.models.train_baselines import choose_numeric_features, _prepare_feature_frame
    frame = _prepare_feature_frame(build_race_training_table("data/processed").replace([np.inf, -np.inf], np.nan))
    chosen, info = choose_numeric_features(frame, [2022, 2023, 2024], ["constructor_prior_mean_finish_3", "constructor_prior_mean_quali_3"])
    assert info["chosen"] in info["validation_brier_by_option"] and "quali_gap_pct" not in chosen   # no lap times exist yet


# ---- the whole lap-time path, with synthetic times (real ones arrive after the next full refresh)
def _with_times(tmp_path):
    import shutil
    shutil.copytree("data/processed", tmp_path / "processed")
    rng = np.random.default_rng(3)
    for f in (tmp_path / "processed").glob("*_qualifying_normalized.csv"):
        q = pd.read_csv(f)
        pole = 80.0
        best = pole + 0.12 * (pd.to_numeric(q["position"], errors="coerce").fillna(20) - 1) + rng.normal(0, 0.03, len(q))
        fmt = lambda t: f"{int(t // 60)}:{t % 60:06.3f}"
        q["q1"] = [fmt(t + 0.6) for t in best]
        q["q2"] = [fmt(t + 0.3) if p <= 15 else None for t, p in zip(best, q["position"])]
        q["q3"] = [fmt(t) if p <= 10 else None for t, p in zip(best, q["position"])]
        q.to_csv(f, index=False)
    return tmp_path / "processed"


def test_lap_times_flow_through_training_table_and_selection(tmp_path):
    from src.features.extra_features import usable_extra_features
    from src.models.train_baselines import _prepare_feature_frame, choose_numeric_features
    table = build_race_training_table(_with_times(tmp_path))
    assert table["quali_gap_pct"].notna().mean() > 0.9 and table["quali_stage_reached"].notna().mean() > 0.9
    assert (table["quali_gap_pct"].dropna() >= 0).all() and table.groupby(["season", "round"])["quali_gap_pct"].min().max() < 1e-9   # pole is 0 everywhere
    table = table.replace([np.inf, -np.inf], np.nan)
    assert {"quali_gap_pct", "quali_stage_reached"} <= set(usable_extra_features(table))
    chosen, info = choose_numeric_features(_prepare_feature_frame(table), [2022, 2023, 2024], usable_extra_features(table))
    assert info["chosen"] in info["validation_brier_by_option"] and "plus team pace and qualifying gaps" in info["validation_brier_by_option"]


def test_lap_times_reach_an_upcoming_race(tmp_path):
    from scripts.predict_upcoming_race import build_upcoming_rows
    processed = _with_times(tmp_path)
    table = build_race_training_table(processed)
    path = tmp_path / "train.csv"
    table.to_csv(path, index=False)
    rows = build_upcoming_rows(2026, 17, processed, path)
    assert rows["quali_gap_pct"].notna().all() and rows["constructor_prior_mean_finish_3"].notna().all()
    same = table[(table["season"] == 2026) & (table["round"] == 17)].set_index("driver_id")
    got = rows.set_index("driver_id")
    for col in ("quali_gap_pct", "quali_stage_reached", "constructor_prior_mean_finish_3"):
        pd.testing.assert_series_equal(got[col].sort_index(), same[col].sort_index(), check_names=False, atol=1e-6)
