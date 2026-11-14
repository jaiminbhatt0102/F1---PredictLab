import pandas as pd
from src.features.build_dataset import build_race_training_table
from scripts.predict_upcoming_race import build_upcoming_rows


def _race(season, rnd, driver, date, pos, points):
    return {"season": season, "round": rnd, "race_name": "Test GP", "race_date": date,
            "circuit_id": "test", "circuit_name": "Test", "driver_id": driver,
            "driver_code": driver.upper(), "constructor_id": "team-a", "constructor_name": "Team A",
            "grid": pos, "position": pos, "points": points, "status": "Finished"}


def test_training_table_joins_sprint_features_and_leaves_non_sprint_missing(tmp_path):
    pd.DataFrame([_race(2025, 1, "driver-a", "2025-03-01", 1, 25),
                  _race(2025, 2, "driver-a", "2025-03-08", 2, 18)]).to_csv(tmp_path / "2025_race_normalized.csv", index=False)
    pd.DataFrame([{"season": 2025, "round": 1, "driver_id": "driver-a", "position": 1},
                  {"season": 2025, "round": 2, "driver_id": "driver-a", "position": 2}]).to_csv(tmp_path / "2025_qualifying_normalized.csv", index=False)
    pd.DataFrame([{"season": 2025, "round": 2, "driver_id": "driver-a", "position": 3, "points": 6}]).to_csv(tmp_path / "2025_sprint_normalized.csv", index=False)
    frame = build_race_training_table(tmp_path)
    first = frame[frame["round"] == 1].iloc[0]
    second = frame[frame["round"] == 2].iloc[0]
    assert pd.isna(first["sprint_position"])
    assert second["sprint_position"] == 3
    assert second["sprint_points"] == 6


def test_upcoming_builder_uses_only_past_race_results(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    pd.DataFrame([{"season": 2025, "round": 3, "race_name": "Test GP", "race_date": "2025-04-01",
                   "circuit_id": "test", "driver_id": "driver-a", "driver_code": "DRA",
                   "constructor_id": "team-a", "constructor_name": "Team A", "position": 2}]).to_csv(
        processed / "2025_qualifying_normalized.csv", index=False)
    history = pd.DataFrame([
        {"season": 2025, "round": 1, "driver_id": "driver-a", "race_date_sort": "2025-03-01",
         "race_position_num": 1, "race_points_num": 25},
        {"season": 2025, "round": 2, "driver_id": "driver-a", "race_date_sort": "2025-03-15",
         "race_position_num": 3, "race_points_num": 15},
        # A future row must not leak into round 3's history.
        {"season": 2025, "round": 4, "driver_id": "driver-a", "race_date_sort": "2025-04-15",
         "race_position_num": 10, "race_points_num": 1},
    ])
    history_path = tmp_path / "history.csv"
    history.to_csv(history_path, index=False)
    result = build_upcoming_rows(2025, 3, processed, history_path)
    assert result.iloc[0]["driver_prior_mean_finish_3"] == 2
    assert result.iloc[0]["driver_prior_mean_points_3"] == 20
    assert result.iloc[0]["qualifying_position"] == 2
