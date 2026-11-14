import pandas as pd
from src.features.build_dataset import build_race_training_table


def _race_row(season, round_no, date, pos, points):
    return {
        "season": season, "round": round_no, "race_name": "Test GP",
        "race_date": date, "circuit_id": "test", "circuit_name": "Test",
        "driver_id": "driver-a", "driver_code": "DRA",
        "constructor_id": "team-a", "constructor_name": "Team A",
        "grid": 1, "position": pos, "points": points, "status": "Finished",
    }


def test_prior_features_do_not_use_current_race_result(tmp_path):
    pd.DataFrame([
        _race_row(2024, 1, "2024-03-01", 1, 25),
        _race_row(2024, 2, "2024-03-08", 3, 15),
    ]).to_csv(tmp_path / "2024_race_normalized.csv", index=False)
    pd.DataFrame([
        {"season": 2024, "round": 1, "driver_id": "driver-a", "position": 1},
        {"season": 2024, "round": 2, "driver_id": "driver-a", "position": 2},
    ]).to_csv(tmp_path / "2024_qualifying_normalized.csv", index=False)
    frame = build_race_training_table(tmp_path)
    second = frame.loc[frame["round"] == 2].iloc[0]
    assert second["driver_prior_mean_finish_3"] == 1.0
    assert second["driver_prior_mean_points_3"] == 25.0
    assert second["target_win"] == 0


def test_driver_history_carries_across_seasons(tmp_path):
    pd.DataFrame([_race_row(2024, 24, "2024-12-01", 2, 18)]).to_csv(
        tmp_path / "2024_race_normalized.csv", index=False
    )
    pd.DataFrame([_race_row(2025, 1, "2025-03-01", 5, 10)]).to_csv(
        tmp_path / "2025_race_normalized.csv", index=False
    )
    frame = build_race_training_table(tmp_path)
    next_season = frame.loc[frame["season"] == 2025].iloc[0]
    assert next_season["driver_prior_mean_finish_3"] == 2.0
    assert next_season["driver_prior_mean_points_3"] == 18.0
    assert next_season["driver_prior_race_count"] == 1
