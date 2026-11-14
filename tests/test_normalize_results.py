import pandas as pd
from src.data.normalize_results import normalize_frame

def test_normalize_converts_numeric_and_adds_event_key():
    raw = pd.DataFrame([{
        "season": "2024", "round": "3", "driver_id": "max_verstappen",
        "position": "1", "points": "25", "race_date": "2024-04-07"
    }])
    result = normalize_frame(raw, "race")
    assert str(result.loc[0, "position"]) == "1"
    assert result.loc[0, "event_key"] == "2024-3"
    assert result.loc[0, "session"] == "race"

def test_normalize_rejects_unknown_session():
    try:
        normalize_frame(pd.DataFrame(), "practice")
    except ValueError as exc:
        assert "Unsupported session" in str(exc)
    else:
        raise AssertionError("Expected unsupported session to fail")
