from datetime import datetime, timedelta, timezone

from src.services import automation as au


def event(rnd=18, start=datetime(2026, 10, 25, 20, tzinfo=timezone.utc), q="pending", sp="not_applicable", race="pending"):
    return {"season": 2026, "round": rnd, "race_name": "Test GP", "race_start_utc": start.isoformat(), "is_sprint_weekend": sp != "not_applicable",
            "sessions": {"qualifying": q, "sprint": sp, "race": race}}


def facts(snaps=(), grid_source=None, official=False, lead_ok=False, state=None):
    return au.Facts(lambda s, r, ses, cp, x: (ses, cp, x) in snaps, lambda s, r: grid_source, lambda s, r: official, lambda s, r: lead_ok,
                    state or {"last_run": {}, "done": {"post_race:2026-17": "x"}})


def ops(actions):
    return [(a.op, a.params.get("checkpoint") or "") for a in actions]


T = datetime(2026, 10, 25, 20, tzinfo=timezone.utc)


def test_nothing_is_due_far_from_a_race():
    got = au.plan(T - timedelta(days=20), [event()], facts(state={"last_run": {"schedule": T.isoformat()}, "done": {}}))
    assert got == []


def test_race_week_before_qualifying():
    got = ops(au.plan(T - timedelta(days=3), [event()], facts(state={"last_run": {"schedule": T.isoformat()}, "done": {}})))
    assert ("fetch_weather_forecast", "") in got and ("refresh_data", "") in got and ("generate_prediction", "pre_qualifying") in got
    assert ("generate_prediction", "post_qualifying") not in got


def test_prediction_is_not_repeated_once_saved():
    got = ops(au.plan(T - timedelta(days=3), [event()], facts(snaps={("qualifying", "pre_qualifying", False)}, state={"last_run": {"schedule": T.isoformat()}, "done": {}})))
    assert ("generate_prediction", "pre_qualifying") not in got


def test_recently_run_steps_wait_for_their_interval():
    now = T - timedelta(days=3)
    state = {"last_run": {"schedule": now.isoformat(), "poll:2026": (now - timedelta(minutes=30)).isoformat(), "forecast:2026-18": (now - timedelta(hours=2)).isoformat()}, "done": {}}
    got = ops(au.plan(now, [event()], facts(state=state)))
    assert ("refresh_data", "") not in got and ("fetch_weather_forecast", "") not in got


def test_forecast_is_refreshed_more_often_the_day_before():
    now = T - timedelta(hours=24)
    state = {"last_run": {"schedule": now.isoformat(), "forecast:2026-18": (now - timedelta(hours=4)).isoformat()}, "done": {}}
    assert ("fetch_weather_forecast", "") in ops(au.plan(now, [event()], facts(state=state)))
    state["last_run"]["forecast:2026-18"] = (now - timedelta(hours=1)).isoformat()
    assert ("fetch_weather_forecast", "") not in ops(au.plan(now, [event()], facts(state=state)))


def test_after_qualifying_makes_the_race_prediction():
    now = T - timedelta(hours=40)
    got = ops(au.plan(now, [event(q="complete")], facts(state={"last_run": {"schedule": now.isoformat()}, "done": {}})))
    assert ("generate_prediction", "post_qualifying") in got and ("fetch_starting_grid", "") in got
    assert ("generate_prediction", "pre_race") not in got                         # too early: more than 30 hours out


def test_sprint_weekend_waits_for_the_sprint():
    now = T - timedelta(hours=40)
    got = ops(au.plan(now, [event(q="complete", sp="pending")], facts(state={"last_run": {"schedule": now.isoformat()}, "done": {}})))
    assert ("generate_prediction", "post_qualifying") not in got


def test_pre_race_waits_for_official_grid_then_falls_back():
    state = lambda n: {"last_run": {"schedule": n.isoformat()}, "done": {}}
    now = T - timedelta(hours=20)
    assert ("generate_prediction", "pre_race") not in ops(au.plan(now, [event(q="complete")], facts(state=state(now))))
    assert ("generate_prediction", "pre_race") in ops(au.plan(now, [event(q="complete")], facts(official=True, state=state(now))))
    late = T - timedelta(hours=5)
    assert ("generate_prediction", "pre_race") in ops(au.plan(late, [event(q="complete")], facts(state=state(late))))


def test_new_snapshot_when_official_grid_arrives_after_fallback():
    now = T - timedelta(hours=10)
    got = ops(au.plan(now, [event(q="complete")], facts(grid_source="qualifying_order", official=True, state={"last_run": {"schedule": now.isoformat()}, "done": {}})))
    assert ("generate_prediction", "pre_race") in got


def test_weather_assisted_only_with_a_usable_forecast():
    now = T - timedelta(hours=10)
    st = {"last_run": {"schedule": now.isoformat()}, "done": {}}
    assert not any(a.params.get("use_weather") for a in au.plan(now, [event(q="complete")], facts(state=dict(st))))
    assert any(a.params.get("use_weather") for a in au.plan(now, [event(q="complete")], facts(lead_ok=True, state=dict(st))))


def test_after_the_race_retrain_once_then_weather():
    done = event(rnd=17, start=T - timedelta(days=2), q="complete", race="complete")
    now = T
    st = {"last_run": {"schedule": now.isoformat()}, "done": {}}
    got = au.plan(now, [done], facts(state=st))
    assert [a.op for a in got][0] == "post_race_update"
    st["done"]["post_race:2026-17"] = "x"
    got = au.plan(now, [done], facts(state=st))
    assert [a.op for a in got] == ["fetch_weather_observed", "train_weather"]
    st["done"]["weather_after:2026-17:a"] = "x"
    assert au.plan(now, [done], facts(state=st)) == []


def test_only_the_latest_finished_race_is_processed():
    old = event(rnd=16, start=T - timedelta(days=10), q="complete", race="complete")
    new = event(rnd=17, start=T - timedelta(days=2), q="complete", race="complete")
    got = au.plan(T, [old, new], facts(state={"last_run": {"schedule": T.isoformat()}, "done": {}}))
    assert [a.params.get("season") for a in got if a.op == "post_race_update"] == [2026] and len([a for a in got if a.op == "post_race_update"]) == 1


def test_run_tick_records_results_and_marks_done(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(au, "manager", type("M", (), {
        "submit": staticmethod(lambda op, params: calls.append(op) or {"job_id": f"j{len(calls)}", "status": "queued"}),
        "get": staticmethod(lambda jid: {"job_id": jid, "status": "succeeded", "error": None}),
    }))
    monkeypatch.setattr(au.ds, "list_events", lambda season: {"events": [event(rnd=17, start=T - timedelta(days=2), q="complete", race="complete")]})
    monkeypatch.setattr(au.ds, "available_seasons", lambda: [2026])
    res = au.run_tick(T, wait=True)
    assert [r["status"] for r in res] and all(r["status"] == "succeeded" for r in res)
    state = au.load_state()
    assert state["bootstrapped"] and "post_race:2026-17" in state["done"]
    assert "weather_after:2026-17:a" in state["done"] and state["last_tick"]["actions"]


def test_failed_source_is_not_hammered_in_one_tick(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(au, "manager", type("M", (), {
        "submit": staticmethod(lambda op, params: calls.append(op) or {"job_id": f"j{len(calls)}", "status": "queued"}),
        "get": staticmethod(lambda jid: {"job_id": jid, "status": "failed", "error": "The data source could not be reached."}),
    }))
    ev = [event(), event(rnd=19, start=T + timedelta(days=14))]
    monkeypatch.setattr(au.ds, "list_events", lambda season: {"events": ev})
    monkeypatch.setattr(au.ds, "available_seasons", lambda: [2026])
    au.run_tick(T - timedelta(days=3), wait=True)
    assert calls.count("refresh_data") <= 1 and calls.count("fetch_weather_forecast") <= 1
