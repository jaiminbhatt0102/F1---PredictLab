import json

from fastapi.testclient import TestClient

from api import main
from api.main import app
from src.services import data_service as svc

client = TestClient(app)


def post(**over):
    body = {"season": 2026, "round": 18, "session": "qualifying", "checkpoint": "pre_qualifying"}
    body.update(over)
    return client.post("/api/v1/predictions", json=body)


def test_health_is_lightweight():
    assert client.get("/health").json()["status"] == "ok"


def test_security_headers_on_every_response():
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store"


def test_status_reports_real_readiness_and_capabilities():
    body = client.get("/api/v1/status").json()
    assert body["status"] in {"ready", "partial", "not_ready"}
    assert body["data"]["seasons"] and body["models"]["production"]
    caps = body["capabilities"]
    assert caps["prediction_history"] and caps["pipeline_jobs"] and caps["predictions_sprint"] and caps["live_predictions"] is False
    assert "automation" in body


def test_events_and_default_round():
    body = client.get("/api/v1/events?season=2026").json()
    assert len(body["events"]) >= 17 and body["default_round"] is not None
    assert "session_times_utc" in body["events"][0]


def test_unknown_season_and_event_are_safe_errors():
    assert client.get("/api/v1/events?season=1900").json()["error"]["code"] == "invalid_season"
    assert client.get("/api/v1/events/2026/99").status_code == 404


def test_invalid_prediction_requests_are_rejected_without_echo():
    assert post(session="qualifying-final").status_code == 422
    assert post(checkpoint="live").status_code == 422
    r = post(session="<script>alert(1)</script>")
    assert r.status_code == 422 and "script" not in r.text


def test_prediction_is_made_and_saved(sandbox):
    r = post().json()
    assert r["status"] == "ready" and r["saved"] and r["snapshot_id"]
    hist = client.get("/api/v1/predictions/history").json()
    assert hist["total"] == 1 and hist["items"][0]["snapshot_id"] == r["snapshot_id"]
    detail = client.get(f"/api/v1/predictions/history/{r['snapshot_id']}").json()
    assert detail["rows"] == r["rows"] and detail["comparison"] is None   # qualifying not run yet
    latest = client.get("/api/v1/predictions/latest/2026/18").json()["items"]
    assert [i["snapshot_id"] for i in latest] == [r["snapshot_id"]]


def test_not_ready_predictions_are_not_saved(sandbox):
    r = post(session="race", checkpoint="post_qualifying").json()
    assert r["status"] == "not_ready" and r["code"] == "qualifying_required" and r["rows"] == []
    assert client.get("/api/v1/predictions/history").json()["total"] == 0


def test_history_filters_and_bad_ids(sandbox):
    post()
    assert client.get("/api/v1/predictions/history?season=2025").json()["total"] == 0
    assert client.get("/api/v1/predictions/history?kind=experimental").json()["total"] == 0
    assert client.get("/api/v1/predictions/history?session=nonsense").status_code == 422
    assert client.get("/api/v1/predictions/history/does-not-exist-1234").status_code == 404
    assert client.get("/api/v1/predictions/history/..%2f..%2fsecret").status_code in (404, 422)


def test_jobs_only_accept_allowlisted_operations(sandbox):
    assert client.post("/api/v1/pipeline/jobs", json={"op": "rm -rf /"}).status_code == 422
    assert client.post("/api/v1/pipeline/jobs", json={"op": "generate_prediction"}).status_code == 422   # not browser-startable
    assert client.post("/api/v1/pipeline/jobs", json={"op": "fetch_weather_forecast", "season": 2026}).status_code == 422


def test_job_can_be_started_and_polled(sandbox, monkeypatch):
    from src.services import pipeline
    monkeypatch.setitem(pipeline.OPERATIONS["refresh_schedule"], "fn", lambda p, c: {"message": "done"})
    job = client.post("/api/v1/pipeline/jobs", json={"op": "refresh_schedule"}).json()
    import time
    for _ in range(100):
        got = client.get(f"/api/v1/pipeline/jobs/{job['job_id']}").json()
        if got["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert got["status"] == "succeeded" and got["summary"]["message"] == "done"
    assert client.get("/api/v1/pipeline/jobs").json()["items"][0]["job_id"] == job["job_id"]


def test_automation_status_is_plain_language():
    body = client.get("/api/v1/automation").json()
    assert body["steps"] and all("label" in s and "when" in s for s in body["steps"])
    assert body["check_every_minutes"] > 0


def test_weather_distinguishes_forecast_from_archive():
    w = client.get("/api/v1/weather/2026/18").json()
    assert w["forecast_snapshots"][0]["kind"] == "forecast_snapshot" and w["historical_archive"] == []
    assert w["forecast_snapshots"][0]["lead_time_check"]["status"] in {"too_early", "ok", "too_late"}


def test_lead_time_contract():
    assert svc._lead_check(222)["status"] == "too_early"
    assert svc._lead_check(24)["status"] == "ok"
    assert svc._lead_check(5)["status"] == "too_late"
    assert svc._lead_check(None)["status"] == "unknown"


def test_models_label_production_candidate_experimental():
    models = client.get("/api/v1/models").json()["models"]
    assert {"production", "candidate", "experimental"} <= {m["status"] for m in models}
    assert "sprint_position" in {m["target"] for m in models}


def test_analysis_endpoints():
    assert client.get("/api/v1/analysis/season/2026").json()["drivers"]
    assert client.get("/api/v1/analysis/constructors/2026").json()["constructors"]
    races = client.get("/api/v1/analysis/circuit/americas").json()["races"]
    assert races and "winner" in races[0]
    assert client.get("/api/v1/analysis/circuit/..%2fx").status_code in (404, 422)
    assert client.get("/api/v1/analysis/circuit/no_such_place").status_code == 404


def test_missing_metric_is_never_zero():
    assert svc._metrics({"brier_score": None}) is None


def test_corrupt_report_returns_safe_error(sandbox):
    (sandbox / "reports" / "model_evaluation.json").write_text("{not json", encoding="utf-8")
    r = client.get("/api/v1/models/evaluations")
    assert r.status_code == 503 and r.json()["error"]["code"] == "report_unreadable" and str(sandbox) not in r.text


def test_responses_never_contain_local_paths():
    for url in ["/api/v1/status", "/api/v1/models", "/api/v1/models/evaluations", "/api/v1/sessions/2026/17", "/api/v1/automation"]:
        text = client.get(url).text
        assert "\\" not in text and str(svc.ROOT) not in text, url


def test_sessions_keep_actual_results_separate():
    s = client.get("/api/v1/sessions/2026/18").json()["sessions"]
    assert s["qualifying"]["rows"] == [] and s["qualifying"]["status"] == "pending"
    done = client.get("/api/v1/sessions/2026/17").json()["sessions"]
    assert done["race"]["status"] == "complete" and done["sprint"]["status"] == "complete"


def test_cors_allows_vite_origin_only():
    ok = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": "http://evil.example"}).headers


def test_oversized_body_rejected():
    r = client.post("/api/v1/predictions", content=json.dumps({"x": "a" * 10000}), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_post_rate_limit(monkeypatch):
    main._post_log.clear()
    monkeypatch.setattr(main, "POSTS_PER_MINUTE", 3)
    codes = [client.post("/api/v1/predictions", json={"season": 2026, "round": 18, "session": "race", "checkpoint": "pre_qualifying"}).status_code for _ in range(5)]
    assert 429 in codes
    main._post_log.clear()


def test_driver_profile_has_real_race_by_race_results():
    d = client.get("/api/v1/drivers/2026/VER").json()
    assert d["driver"]["code"] == "VER" and d["standing"]["rank"] and d["standing"]["races"] == len(d["results"])
    first = d["results"][0]
    assert {"round", "grid", "position", "points", "qualifying_position"} <= set(first)
    assert d["driver"]["team_slug"] == "red-bull" and 2026 in d["seasons_with_data"]


def test_driver_and_team_errors_are_safe():
    assert client.get("/api/v1/drivers/2026/ZZZ").status_code == 404
    assert client.get("/api/v1/drivers/2026/..%2f").status_code in (404, 422)
    assert client.get("/api/v1/drivers/2026/TOOLONGCODE").status_code == 422
    assert client.get("/api/v1/teams/2026/not-a-team").status_code == 404
    assert client.get("/api/v1/drivers/1900/VER").status_code == 422


def test_team_profile_lists_lineup_and_rounds():
    t = client.get("/api/v1/teams/2026/red-bull").json()
    assert t["team"]["name"] == "Red Bull" and t["standing"]["rank"] and len(t["drivers"]) >= 2
    assert t["rounds"] and all(r["drivers"] for r in t["rounds"]) and "\\" not in str(t)
