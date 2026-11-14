import time

import pytest

from src.services import data_service as ds
from src.services import pipeline


@pytest.fixture
def mgr(sandbox):
    return pipeline.JobManager()


def wait(m, job_id, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        job = m.get(job_id)
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_only_allowlisted_operations(mgr):
    for bad in ("rm -rf /", "refresh_data; echo hi", "", "../scripts/x"):
        with pytest.raises(ds.ServiceError) as e:
            mgr.submit(bad)
        assert e.value.code == "unknown_operation"


def test_parameters_are_validated(mgr):
    with pytest.raises(ds.ServiceError):
        mgr.submit("fetch_weather_forecast", {"season": "2026; ls", "round": 18})
    with pytest.raises(ds.ServiceError) as e:
        mgr.submit("fetch_weather_forecast", {"season": 2026})
    assert e.value.code == "missing_parameter"
    with pytest.raises(ds.ServiceError) as e:
        mgr.submit("fetch_weather_forecast", {"season": 2026, "round": 99})
    assert e.value.http_status == 404


def test_job_runs_and_is_recorded(mgr, monkeypatch):
    monkeypatch.setitem(pipeline.OPERATIONS["refresh_schedule"], "fn", lambda p, c: {"message": "ok"})
    job = mgr.submit("refresh_schedule")
    done = wait(mgr, job["job_id"])
    assert done["status"] == "succeeded" and done["summary"]["message"] == "ok"
    assert mgr.list(5)[0]["job_id"] == job["job_id"]


def test_identical_pending_work_is_not_queued_twice(mgr, monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setitem(pipeline.OPERATIONS["refresh_schedule"], "fn", lambda p, c: gate.wait(5) and {"message": "ok"})
    a = mgr.submit("refresh_schedule")
    b = mgr.submit("refresh_schedule")
    assert a["job_id"] == b["job_id"]
    gate.set()
    wait(mgr, a["job_id"])


def test_failure_message_is_safe(mgr, monkeypatch):
    def boom(p, c):
        raise RuntimeError(r"C:\Users\Admin\secret\path.py line 3 Traceback")
    monkeypatch.setitem(pipeline.OPERATIONS["refresh_schedule"], "fn", boom)
    done = wait(mgr, mgr.submit("refresh_schedule")["job_id"])
    assert done["status"] == "failed" and "Admin" not in done["error"] and "Traceback" not in done["error"]


def test_job_error_message_is_passed_through(mgr, monkeypatch):
    def fail(p, c):
        raise pipeline.JobError("The data source could not be reached. Check the internet connection and try again.")
    monkeypatch.setitem(pipeline.OPERATIONS["refresh_schedule"], "fn", fail)
    done = wait(mgr, mgr.submit("refresh_schedule")["job_id"])
    assert "internet" in done["error"]


def test_queue_is_bounded(mgr, monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setitem(pipeline.OPERATIONS["refresh_schedule"], "fn", lambda p, c: gate.wait(5))
    monkeypatch.setattr(pipeline, "MAX_QUEUED", 2)
    mgr._q = pipeline.queue.Queue(maxsize=2)
    mgr.submit("refresh_schedule")
    time.sleep(0.3)                                           # first job starts running and leaves the queue
    mgr.submit("train_weather"); mgr.submit("refresh_data")
    with pytest.raises(ds.ServiceError) as e:
        mgr.submit("train_models")
    assert e.value.code == "queue_full"
    gate.set()


def test_interrupted_jobs_are_marked_failed_on_restart(mgr):
    mgr._save({"job_id": "20260101T000000-abc123", "op": "refresh_data", "label": "x", "params": {}, "status": "running",
               "created_at_utc": "2026-01-01T00:00:00+00:00", "started_at_utc": None, "finished_at_utc": None, "summary": None, "error": None})
    mgr.recover()
    assert pipeline.JobManager().get("20260101T000000-abc123")["status"] == "failed"


def test_job_id_cannot_traverse(mgr):
    for bad in ("../x", "a/b", "x" * 80):
        with pytest.raises(ds.ServiceError):
            mgr.get(bad)


def test_script_runner_uses_fixed_argument_list(mgr, monkeypatch):
    seen = {}

    class P:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(cmd, **kw):
        seen["cmd"], seen["shell"] = cmd, kw.get("shell", False)
        return P()

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    pipeline.op_fetch_weather_forecast({"season": 2026, "round": 18}, {"log": ds.ROOT / "x.log"})
    assert seen["shell"] is False and seen["cmd"][-4:] == ["--season", "2026", "--round", "18"]


def test_network_failure_is_explained_kindly():
    assert "internet" in pipeline._friendly("x.py", "httpx.ConnectError: [Errno -3] Temporary failure in name resolution")
    assert "slow down" in pipeline._friendly("x.py", "HTTP 429 Too Many Requests")


def test_weather_api_failure_is_recognised_as_a_network_problem():
    text = "RuntimeError: Weather API request failed: <urlopen error [Errno -2] Name or service not known>"
    assert "internet" in pipeline._friendly("fetch_event_weather.py", text)
