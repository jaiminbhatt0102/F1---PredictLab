import json

import pytest

from src.services import data_service as ds
from src.services import predictor, snapshots


def gen(*a, **k):
    return predictor.generate(*a, **k)


def test_before_qualifying_saves_snapshot(sandbox):
    r = gen(2026, 18, "qualifying", "pre_qualifying")
    assert r["status"] == "ready" and r["saved"] and len(r["rows"]) >= 20
    assert [x["predicted_order"] for x in r["rows"]] == list(range(1, len(r["rows"]) + 1))
    assert r["inputs"]["weather"]["lead_time_check"]["status"] in {"too_early", "ok", "too_late", "unknown"}
    assert snapshots.get(r["snapshot_id"])["rows"] == r["rows"]


def test_stage_rules_block_leakage(sandbox):
    assert gen(2026, 18, "race", "post_qualifying")["code"] == "qualifying_required"
    assert gen(2026, 18, "race", "pre_race")["code"] == "qualifying_required"
    assert gen(2026, 18, "race", "pre_qualifying")["code"] == "stage_not_supported"
    assert gen(2026, 18, "qualifying", "pre_race")["code"] == "stage_not_supported"
    assert gen(2026, 18, "sprint", "pre_sprint")["code"] == "no_sprint"


def test_finished_sessions_cannot_be_predicted_again(sandbox):
    for session, cp in (("qualifying", "pre_qualifying"), ("sprint", "pre_sprint"), ("race", "post_qualifying"), ("race", "pre_race")):
        assert gen(2026, 17, session, cp)["code"] == "already_happened"
    assert snapshots.list_snapshots()["total"] == 0


def test_cannot_skip_ahead_of_missing_races(sandbox):
    assert gen(2026, 19, "qualifying", "pre_qualifying")["code"] == "earlier_race_missing"


def test_after_qualifying_race_prediction(after_qualifying):
    r = gen(2026, 17, "race", "post_qualifying")
    assert r["status"] == "ready" and r["kind"] == "production"
    assert all(0 <= x["win_probability"] <= 1 and 0 <= x["podium_probability"] <= 1 for x in r["rows"])
    assert [x["win_rank"] for x in r["rows"]] == list(range(1, len(r["rows"]) + 1))
    assert r["inputs"]["grid_source"] == "qualifying_order"
    assert any("Penalties" in w for w in r["warnings"])


def test_before_race_uses_official_grid_when_published(after_qualifying):
    base = gen(2026, 17, "race", "pre_race")
    assert base["inputs"]["grid_source"] == "qualifying_order"
    ids = [x["driver_id"] for x in base["rows"]]
    grid = "season,round,driver_id,grid\n" + "\n".join(f"2026,17,{d},{i + 1}" for i, d in enumerate(reversed(ids)))
    (ds.ROOT / "data/processed/2026_starting_grid.csv").write_text(grid, encoding="utf-8")
    official = gen(2026, 17, "race", "pre_race")
    assert official["inputs"]["grid_source"] == "official_grid"
    assert official["snapshot_id"] != base["snapshot_id"]            # new snapshot, old one untouched
    assert snapshots.get(base["snapshot_id"])["inputs"]["grid_source"] == "qualifying_order"


def test_incomplete_grid_file_falls_back_with_warning(after_qualifying):
    (ds.ROOT / "data/processed/2026_starting_grid.csv").write_text("season,round,driver_id,grid\n2026,17,max_verstappen,1\n", encoding="utf-8")
    r = gen(2026, 17, "race", "pre_race")
    assert r["inputs"]["grid_source"] == "qualifying_order"
    assert any("doesn’t cover every driver" in w for w in r["warnings"])


def test_weather_view_needs_a_forecast_in_the_lead_window(after_qualifying):
    r = gen(2026, 17, "race", "pre_race", use_weather=True)
    assert r["status"] == "not_ready" and r["code"] in {"weather_missing", "weather_lead_time"}


def test_weather_view_runs_when_contract_is_met(after_qualifying):
    path = ds.ROOT / "data/processed/weather_forecast_snapshots.csv"
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    row = dict.fromkeys(header, "")
    row.update(season="2026", round="17", race_name="Singapore Grand Prix", circuit_id="marina_bay", race_start_utc="2026-10-11T12:00:00+00:00",
               weather_valid_time_utc="2026-10-11T12:00:00+00:00", fetched_at_utc="2026-10-10T12:00:00+00:00", forecast_lead_hours="24.0",
               api_status="ok", temperature_c="29.5", precipitation_mm="0", weather_source="Open-Meteo Forecast API")
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write("\n" + ",".join(row[h] for h in header) + "\n")
    r = gen(2026, 17, "race", "pre_race", use_weather=True)
    assert r["status"] == "ready" and r["kind"] == "experimental" and r["model"]["status"] == "experimental"
    assert any("Experimental" in w for w in r["warnings"])


def test_weather_view_not_for_qualifying(sandbox):
    assert gen(2026, 18, "qualifying", "pre_qualifying", use_weather=True)["code"] == "weather_race_only"


def test_model_that_saw_the_event_is_refused(before_sprint):
    # The shipped sprint model was trained through round 17, so predicting round 17 would be unfair.
    r = gen(2026, 17, "sprint", "pre_sprint")
    assert r["status"] == "not_ready" and r["code"] == "model_saw_event"


def test_sprint_prediction_with_a_model_trained_on_earlier_data(before_sprint):
    from src.models.train_sprint import train_sprint_model

    models = ds.ROOT / "models"
    models.unlink()
    models.mkdir()
    train_sprint_model(ds.ROOT / "data/processed", ds.ROOT / "data/features/race_training.csv", models, ds.ROOT / "reports/sprint_eval_test.json")
    r = gen(2026, 17, "sprint", "pre_sprint")
    assert r["status"] == "ready" and r["output_type"] == "predicted_sprint_position"
    assert any("rough" in w for w in r["warnings"])


def test_missing_model_is_a_safe_not_ready(after_qualifying):
    (ds.ROOT / "models").unlink()
    (ds.ROOT / "models").mkdir()
    r = gen(2026, 17, "race", "post_qualifying")
    assert r["status"] == "not_ready" and r["code"] == "model_missing"
    assert str(ds.ROOT) not in json.dumps(r)


def test_snapshots_are_immutable(sandbox):
    r = gen(2026, 18, "qualifying", "pre_qualifying")
    with pytest.raises(ds.ServiceError) as err:
        snapshots.save({**snapshots.get(r["snapshot_id"])})
    assert err.value.code == "snapshot_exists"
    again = gen(2026, 18, "qualifying", "pre_qualifying")
    assert again["snapshot_id"] != r["snapshot_id"] and snapshots.list_snapshots()["total"] == 2


def test_snapshot_id_cannot_escape_the_folder(sandbox):
    for bad in ("../secrets", "a/b", "..\\x", "x" * 300):
        with pytest.raises(ds.ServiceError):
            snapshots.get(bad)


def test_history_filters_and_comparison(after_qualifying):
    r = gen(2026, 17, "race", "post_qualifying")
    assert snapshots.list_snapshots(season=2026, session="race")["total"] == 1
    assert snapshots.list_snapshots(session="qualifying")["total"] == 0
    assert snapshots.compare_with_results(snapshots.get(r["snapshot_id"])) is None  # race not run yet in this sandbox


def test_comparison_after_the_real_result_exists(sandbox):
    # Build a snapshot for round 17 by hand from the stored production output, then compare with the real race.
    import pandas as pd
    stored = pd.read_csv(ds.ROOT / "reports/upcoming_race_predictions.csv")
    rows = [{"driver_code": r.driver_code, "driver_name": f"{r.driver_given_name} {r.driver_family_name}", "win_probability": r.target_win_probability,
             "podium_probability": r.target_podium_probability} for r in stored.itertuples()]
    snap = {"snapshot_id": "2026-r17-race-post_qualifying-p-20261011T000000Z-aaaa", "requested": {"season": 2026, "round": 17, "session": "race", "checkpoint": "post_qualifying"},
            "output_type": "win_and_podium_probability", "rows": rows}
    cmp = snapshots.compare_with_results(snap)
    assert cmp["kind"] == "race" and cmp["headline"]["podium_picks"] == 3 and cmp["headline"]["actual_winner"]
    assert len(cmp["rows"]) >= 20


def test_track_record_counts_each_stage_once(sandbox):
    assert snapshots.track_record()["race"]["compared"] == 0
    import pandas as pd
    stored = pd.read_csv(ds.ROOT / "reports/upcoming_race_predictions.csv")
    rows = [{"driver_code": r.driver_code, "driver_name": f"{r.driver_given_name} {r.driver_family_name}", "win_probability": r.target_win_probability,
             "podium_probability": r.target_podium_probability} for r in stored.itertuples()]
    base = {"requested": {"season": 2026, "round": 17, "session": "race", "checkpoint": "post_qualifying"}, "kind": "production", "output_type": "win_and_podium_probability",
            "rows": rows, "model": {}, "stage": {}, "event_name": "x", "trigger": "automatic"}
    snapshots.save({**base, "snapshot_id": "2026-r17-race-post_qualifying-p-20261011T000000Z-aaaa", "created_at_utc": "2026-10-10T10:00:00+00:00"})
    snapshots.save({**base, "snapshot_id": "2026-r17-race-post_qualifying-p-20261011T010000Z-bbbb", "created_at_utc": "2026-10-10T11:00:00+00:00"})
    rec = snapshots.track_record()
    assert rec["race"]["compared"] == 1 and rec["race"]["podium_picks"] == 3
