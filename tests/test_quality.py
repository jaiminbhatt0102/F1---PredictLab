import pandas as pd
from src.data.quality import inspect_csv, build_coverage_report

def test_inspect_csv_detects_duplicate_keys(tmp_path):
    path = tmp_path / "2024_race_results.csv"
    pd.DataFrame([
        {"season": 2024, "round": 1, "driver_id": "driver-a", "position": 1},
        {"season": 2024, "round": 1, "driver_id": "driver-a", "position": 2},
    ]).to_csv(path, index=False)
    result = inspect_csv(path)
    assert result["rows"] == 2
    assert result["duplicate_event_driver_keys"] == 1

def test_coverage_report_warns_when_no_files(tmp_path):
    result = build_coverage_report(tmp_path)
    assert result["files_found"] == 0
    assert any("No *_results.csv" in warning for warning in result["warnings"])
