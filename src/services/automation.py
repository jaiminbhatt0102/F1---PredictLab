"""Race-weekend automation.

`plan()` is a pure function: given the time, the events, what has already run and what
data exists, it returns the steps that are due. `run_tick()` executes them through the
pipeline job manager. `Scheduler` calls run_tick() on a timer inside the API process,
and scripts/run_automation.py can run one tick from Windows Task Scheduler.

Data-driven by design: it does not assume session start times. It polls for results
during race week and reacts when qualifying, sprint or race data actually appears.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from collections.abc import Callable

import pandas as pd

from src.services import data_service as ds
from src.services import snapshots
from src.services.pipeline import manager

log = logging.getLogger("f1_predictlab.automation")
POLL_INTERVAL = timedelta(hours=2)
FORECAST_DAILY = timedelta(hours=24)
FORECAST_NEAR_RACE = timedelta(hours=3)
ATTEMPT_INTERVAL = timedelta(hours=3)
SCHEDULE_INTERVAL = timedelta(days=7)


@dataclass
class Action:
    op: str
    params: dict
    key: str
    reason: str
    mark_done: bool = False
    also_done: list[str] = field(default_factory=list)


@dataclass
class Facts:
    """Everything the planner needs to know, injected so it can be tested."""
    has_snapshot: Callable[[int, int, str, str, bool], bool]
    grid_source_of_latest: Callable[[int, int], str | None]
    official_grid_exists: Callable[[int, int], bool]
    forecast_lead_ok: Callable[[int, int], bool]
    state: dict = field(default_factory=lambda: {"last_run": {}, "done": {}})


def _due(state: dict, key: str, now: datetime, interval: timedelta) -> bool:
    last = state["last_run"].get(key)
    return last is None or now - datetime.fromisoformat(last) >= interval


def plan(now: datetime, events: list[dict], facts: Facts) -> list[Action]:
    state = facts.state
    actions: list[Action] = []
    if _due(state, "schedule", now, SCHEDULE_INTERVAL):
        actions.append(Action("refresh_schedule", {}, "schedule", "Weekly schedule check"))

    completed = [e["round"] for e in events if e["sessions"]["race"] == "complete"]
    latest_done = max(completed) if completed else None
    for ev in events:
        if not ev.get("race_start_utc"):
            continue
        start = pd.Timestamp(ev["race_start_utc"]).to_pydatetime()
        s, r = ev["season"], ev["round"]
        tag = f"{s}-{r}"
        until = start - now
        s_state = ev["sessions"]
        q_done, r_done = s_state["qualifying"] == "complete", s_state["race"] == "complete"
        sprint_weekend = ev["is_sprint_weekend"]
        sp_done = s_state["sprint"] == "complete"

        # ---- before the race
        if not r_done and timedelta(hours=-3) <= until <= timedelta(days=8):
            near = timedelta(hours=18) <= until <= timedelta(hours=30)
            interval = FORECAST_NEAR_RACE if near else FORECAST_DAILY
            if until > timedelta(0) and _due(state, f"forecast:{tag}", now, interval):
                actions.append(Action("fetch_weather_forecast", {"season": s, "round": r}, f"forecast:{tag}", "Race-week weather forecast"))
        if not r_done and timedelta(days=-2) <= until <= timedelta(days=4):
            if _due(state, f"poll:{s}", now, POLL_INTERVAL):
                actions.append(Action("refresh_data", {"season": s}, f"poll:{s}", "Looking for new session results"))

        if not q_done and timedelta(0) < until <= timedelta(days=5):
            if not facts.has_snapshot(s, r, "qualifying", "pre_qualifying", False) and _due(state, f"pred:{tag}:pq", now, ATTEMPT_INTERVAL):
                actions.append(Action("generate_prediction", {"season": s, "round": r, "session": "qualifying", "checkpoint": "pre_qualifying", "trigger": "automatic"}, f"pred:{tag}:pq", "Prediction before qualifying"))
        if sprint_weekend and not sp_done and timedelta(0) < until <= timedelta(days=4):
            if not facts.has_snapshot(s, r, "sprint", "pre_sprint", False) and _due(state, f"pred:{tag}:ps", now, ATTEMPT_INTERVAL):
                actions.append(Action("generate_prediction", {"season": s, "round": r, "session": "sprint", "checkpoint": "pre_sprint", "trigger": "automatic"}, f"pred:{tag}:ps", "Prediction before the sprint"))

        # ---- qualifying (and sprint) finished, race not run
        race_ready = q_done and (sp_done or not sprint_weekend) and not r_done
        if race_ready:
            if not facts.has_snapshot(s, r, "race", "post_qualifying", False) and _due(state, f"pred:{tag}:pq2", now, ATTEMPT_INTERVAL):
                actions.append(Action("generate_prediction", {"season": s, "round": r, "session": "race", "checkpoint": "post_qualifying", "trigger": "automatic"}, f"pred:{tag}:pq2", "Race prediction after qualifying"))
            if not facts.official_grid_exists(s, r) and _due(state, f"grid:{tag}", now, ATTEMPT_INTERVAL):
                actions.append(Action("fetch_starting_grid", {"season": s, "round": r}, f"grid:{tag}", "Checking for the starting grid"))
            if until <= timedelta(hours=30):
                latest_src = facts.grid_source_of_latest(s, r)
                need = latest_src is None or (latest_src != "official_grid" and facts.official_grid_exists(s, r))
                if latest_src is None and until > timedelta(hours=6) and not facts.official_grid_exists(s, r):
                    need = False  # wait for the grid; fall back to the qualifying order in the last 6 hours
                if need and _due(state, f"pred:{tag}:pr", now, ATTEMPT_INTERVAL):
                    actions.append(Action("generate_prediction", {"season": s, "round": r, "session": "race", "checkpoint": "pre_race", "trigger": "automatic"}, f"pred:{tag}:pr", "Race prediction before the race"))
                if facts.forecast_lead_ok(s, r) and not facts.has_snapshot(s, r, "race", "pre_race", True) and _due(state, f"pred:{tag}:prw", now, ATTEMPT_INTERVAL):
                    actions.append(Action("generate_prediction", {"season": s, "round": r, "session": "race", "checkpoint": "pre_race", "use_weather": True, "trigger": "automatic"}, f"pred:{tag}:prw", "Weather-assisted race prediction (experimental)"))

        # ---- after the race
        if r_done and ev["round"] == latest_done and now - start < timedelta(days=21):
            if f"post_race:{tag}" not in state["done"]:
                actions.append(Action("post_race_update", {"season": s}, f"post_race:{tag}", "Adding the new race result and retraining", mark_done=True))
            elif now - start >= timedelta(hours=26):
                due = [(l, a) for l, a in (("a", timedelta(hours=26)), ("b", timedelta(days=6)))
                       if now - start >= a and f"weather_after:{tag}:{l}" not in state["done"]]
                if due:
                    key = f"weather_after:{tag}:{due[-1][0]}"
                    actions.append(Action("fetch_weather_observed", {"season": s, "round": r}, f"{key}:obs", "Saving the actual race-day weather"))
                    actions.append(Action("train_weather", {}, key, "Retraining the weather models", mark_done=True,
                                          also_done=[f"weather_after:{tag}:{l}" for l, _ in due[:-1]]))
    return actions


# ----------------------------------------------------------------------- facts
def _state_path():
    return ds.ROOT / "data" / "automation_state.json"


def load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        data.setdefault("last_run", {})
        data.setdefault("done", {})
        return data
    except (OSError, ValueError):
        return {"last_run": {}, "done": {}}


def save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def real_facts(state: dict) -> Facts:
    def has_snapshot(s: int, r: int, session: str, checkpoint: str, experimental: bool) -> bool:
        return snapshots.latest_for(s, r, session, checkpoint, experimental) is not None

    def grid_source(s: int, r: int) -> str | None:
        item = snapshots.latest_for(s, r, "race", "pre_race", False)
        if not item:
            return None
        return (snapshots.get(item["snapshot_id"]).get("inputs") or {}).get("grid_source")

    def official(s: int, r: int) -> bool:
        return (ds.ROOT / "data" / "processed" / f"{s}_starting_grid.csv").exists() and _grid_rows(s, r)

    def lead_ok(s: int, r: int) -> bool:
        try:
            snaps = ds.get_weather(s, r)["forecast_snapshots"]
        except ds.ServiceError:
            return False
        return bool(snaps) and snaps[0]["lead_time_check"]["status"] == "ok"

    return Facts(has_snapshot, grid_source, official, lead_ok, state)


def _grid_rows(s: int, r: int) -> bool:
    try:
        frame = pd.read_csv(ds.ROOT / "data" / "processed" / f"{s}_starting_grid.csv")
        return bool(((frame["season"] == s) & (frame["round"] == r)).any())
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------------ runner
def _wait(job_id: str, timeout_s: int = 7200) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = manager.get(job_id)
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(2)
    return manager.get(job_id)


def run_tick(now: datetime | None = None, wait: bool = True) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    state = load_state()
    try:
        season = ds.available_seasons()[-1]
        events = ds.list_events(season)["events"]
    except ds.ServiceError as exc:
        state["last_tick"] = {"at_utc": now.isoformat(), "note": exc.message, "actions": []}
        save_state(state)
        return []
    if not state.get("bootstrapped"):
        # Races already in the data when automation first runs were handled by the existing
        # manual workflow; do not retrain for them. Weather catch-up is still allowed.
        for e in events:
            if e["sessions"]["race"] == "complete":
                state["done"][f"post_race:{e['season']}-{e['round']}"] = now.isoformat()
        state["bootstrapped"] = True
        save_state(state)
    actions = plan(now, events, real_facts(state))
    results = []
    failed_scope: set[str] = set()
    for act in actions:
        if act.op in failed_scope:
            continue
        job = manager.submit(act.op, act.params)
        state["last_run"][act.key] = now.isoformat()
        if wait:
            job = _wait(job["job_id"])
        ok = job["status"] == "succeeded"
        if ok and act.mark_done:
            for k in [act.key, *act.also_done]:
                state["done"][k] = _now_iso()
        if not ok and act.op in ("refresh_data", "fetch_weather_forecast", "refresh_schedule"):
            failed_scope.add(act.op)  # source unreachable; do not hammer it in the same tick
        results.append({"op": act.op, "reason": act.reason, "job_id": job["job_id"], "status": job["status"], "error": job.get("error")})
        save_state(state)
    state["last_tick"] = {"at_utc": now.isoformat(), "note": None, "actions": results}
    save_state(state)
    return results


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Scheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.interval_s = int(os.getenv("AUTOMATION_INTERVAL_MIN", "15")) * 60
        self.last_error: str | None = None

    @staticmethod
    def enabled() -> bool:
        return os.getenv("AUTOMATION_ENABLED", "1") not in ("0", "false", "False", "no")

    def start(self) -> bool:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return False
        manager.recover()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="automation", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        self._stop.wait(20)  # let the API finish starting
        while not self._stop.is_set():
            try:
                run_tick()
                self.last_error = None
            except Exception:  # noqa: BLE001
                log.exception("Automation tick failed")
                self.last_error = "The last automatic check hit an unexpected problem. See the server log."
            self._stop.wait(self.interval_s)


scheduler = Scheduler()


# ----------------------------------------------------------------------- status
def describe(now: datetime | None = None) -> dict:
    """Plain-language status for the Updates page."""
    now = now or datetime.now(timezone.utc)
    state = load_state()
    last = state.get("last_tick")
    steps = [
        {"label": "Race schedule", "when": "Checked once a week."},
        {"label": "Weather forecast", "when": "Saved daily in race week, and every 3 hours the day before the race."},
        {"label": "New session results", "when": "Checked every 2 hours from 4 days before the race until 2 days after."},
        {"label": "Prediction before qualifying", "when": "Made automatically in the 5 days before the race, once."},
        {"label": "Prediction before the sprint", "when": "Sprint weekends only, in the 4 days before the race."},
        {"label": "Race prediction after qualifying", "when": "As soon as qualifying (and the sprint) results appear."},
        {"label": "Race prediction before the race", "when": "Within 30 hours of the start, using the official grid when it is available."},
        {"label": "After the race", "when": "The result is added, the models are retrained, and the actual weather is saved."},
    ]
    return {
        "enabled": scheduler.enabled(),
        "running": scheduler.running(),
        "check_every_minutes": scheduler.interval_s // 60,
        "last_check": last,
        "last_problem": scheduler.last_error,
        "steps": steps,
        "recent_jobs": manager.list(8),
        "busy": manager.busy(),
    }
