"""Allowlisted pipeline operations and a small, bounded job manager.

Safety rules:
- The browser (or automation) can only name an operation from OPERATIONS.
- Parameters are validated integers or literals; nothing is ever put in a shell.
- Scripts run via subprocess with a fixed argument list and a timeout.
- One job runs at a time; the waiting queue is bounded.
- Job records are saved as JSON. Raw output and tracebacks go to a server-side log file
  and are never returned to callers.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services import data_service as ds

log = logging.getLogger("f1_predictlab.pipeline")
MAX_QUEUED = 6
KEEP_LISTED = 40
SCRIPT_TIMEOUT_S = 3600


class JobError(Exception):
    """A failure with a message that is safe to show to a user."""


# ---------------------------------------------------------------- script runner
def _run_script(args: list[str], timeout: int = SCRIPT_TIMEOUT_S, log_path: Path | None = None) -> None:
    script = ds.ROOT / "scripts" / args[0]
    if not script.exists():
        raise JobError("A required pipeline script is missing from the project.")
    cmd = [sys.executable, str(script), *args[1:]]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(cmd, cwd=str(ds.ROOT), capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise JobError("This step took too long and was stopped.") from exc
    except OSError as exc:
        raise JobError("This step could not be started.") from exc
    if log_path is not None:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"$ {' '.join(args)}\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}\n")
    if proc.returncode != 0:
        raise JobError(_friendly(args[0], proc.stderr + proc.stdout))


def _friendly(script: str, output: str) -> str:
    text = output.lower()
    if any(k in text for k in ("connecterror", "connection", "timed out", "name resolution", "getaddrinfo", "network", "urlopen", "name or service not known", "temporary failure", "unreachable", "api request failed", "ssl")):
        return "The data source could not be reached. Check the internet connection and try again."
    if "429" in text or "too many requests" in text:
        return "The data source asked us to slow down. It will be retried later."
    return "This step failed. The details are saved in the server log."


# ------------------------------------------------------------------- operations
def _season_param(params: dict) -> int:
    return int(params.get("season") or ds.available_seasons()[-1])


def _next_event(season: int) -> dict | None:
    data = ds.list_events(season)
    for ev in data["events"]:
        if ev["weekend_stage"] != "race_complete":
            return ev
    return None


def op_refresh_data(params: dict, ctx: dict) -> dict:
    season = _season_param(params)
    _run_script(["collect_f1_data.py", "--start", str(season), "--end", str(season), "--refresh"], log_path=ctx["log"])
    _run_script(["normalize_f1_data.py"], log_path=ctx["log"])
    _run_script(["build_race_dataset.py"], log_path=ctx["log"])
    return {"season": season, "message": f"Race data for {season} updated."}


def op_refresh_schedule(params: dict, ctx: dict) -> dict:
    _run_script(["build_f1_schedule.py"], log_path=ctx["log"])
    return {"message": "Race schedule updated."}


def op_fetch_weather_forecast(params: dict, ctx: dict) -> dict:
    _run_script(["fetch_event_weather.py", "forecast", "--season", str(params["season"]), "--round", str(params["round"])], log_path=ctx["log"])
    return {"message": "Weather forecast saved as a new snapshot."}


def op_fetch_weather_observed(params: dict, ctx: dict) -> dict:
    _run_script(["fetch_event_weather.py", "observed", "--season", str(params["season"]), "--round", str(params["round"])], log_path=ctx["log"])
    return {"message": "Race-day weather record saved."}


def op_fetch_starting_grid(params: dict, ctx: dict) -> dict:
    _run_script(["fetch_starting_grid.py", "--season", str(params["season"]), "--round", str(params["round"])], log_path=ctx["log"])
    return {"message": "Starting grid checked."}


def op_train_models(params: dict, ctx: dict) -> dict:
    season = _season_param(params)
    _run_script(["train_f1_models.py"], log_path=ctx["log"])
    _run_script(["train_sprint_model.py"], log_path=ctx["log"])
    target = _next_event(season)
    if target and target.get("circuit_id"):
        _run_script(["predict_qualifying.py", "--season", str(target["season"]), "--round", str(target["round"]), "--circuit-id", target["circuit_id"]], log_path=ctx["log"])
        note = f"Models retrained; qualifying model prepared for round {target['round']}."
    else:
        note = "Race and sprint models retrained. No upcoming event was found for the qualifying model."
    return {"message": note}


def op_backfill_history(params: dict, ctx: dict) -> dict:
    """Re-download every season (adds qualifying lap times to history), rebuild and retrain. Slow; run once."""
    seasons = ds.available_seasons()
    _run_script(["collect_f1_data.py", "--start", str(seasons[0]), "--end", str(seasons[-1]), "--refresh"], log_path=ctx["log"])
    _run_script(["normalize_f1_data.py"], log_path=ctx["log"])
    _run_script(["build_race_dataset.py"], log_path=ctx["log"])
    op_train_models({"season": seasons[-1]}, ctx)
    return {"message": "History re-downloaded with qualifying lap times and the models were retrained."}


def op_train_weather(params: dict, ctx: dict) -> dict:
    _run_script(["build_weather_forecasts.py"], log_path=ctx["log"])
    _run_script(["run_weather_all_models_experiment.py"], log_path=ctx["log"])
    _run_script(["train_weather_candidates.py"], log_path=ctx["log"])
    return {"message": "Experimental weather models retrained from past forecasts."}


def op_post_race_update(params: dict, ctx: dict) -> dict:
    op_refresh_data(params, ctx)
    op_train_models(params, ctx)
    return {"message": "New race result added and models retrained."}


def op_generate_prediction(params: dict, ctx: dict) -> dict:
    from src.services import predictor

    res = predictor.generate(params["season"], params["round"], params["session"], params["checkpoint"], bool(params.get("use_weather")), trigger=params.get("trigger", "automatic"))
    if res["status"] != "ready":
        return {"message": res.get("message") or "Not ready.", "skipped": True, "code": res.get("code")}
    return {"message": "Prediction saved.", "snapshot_id": res["snapshot_id"]}


OPERATIONS: dict[str, dict[str, Any]] = {
    "refresh_data": {"label": "Update race results", "fn": op_refresh_data, "needs": []},
    "refresh_schedule": {"label": "Update the race schedule", "fn": op_refresh_schedule, "needs": []},
    "fetch_weather_forecast": {"label": "Get the weather forecast", "fn": op_fetch_weather_forecast, "needs": ["season", "round"]},
    "fetch_weather_observed": {"label": "Save the actual race weather", "fn": op_fetch_weather_observed, "needs": ["season", "round"]},
    "fetch_starting_grid": {"label": "Check for the starting grid", "fn": op_fetch_starting_grid, "needs": ["season", "round"]},
    "train_models": {"label": "Retrain the prediction models", "fn": op_train_models, "needs": []},
    "backfill_history": {"label": "Add qualifying lap times to history", "fn": op_backfill_history, "needs": []},
    "train_weather": {"label": "Retrain the weather models", "fn": op_train_weather, "needs": []},
    "post_race_update": {"label": "Add the latest race and retrain", "fn": op_post_race_update, "needs": []},
    "generate_prediction": {"label": "Make a prediction", "fn": op_generate_prediction, "needs": ["season", "round", "session", "checkpoint"]},
}


def validate_params(op: str, params: dict) -> dict:
    if op not in OPERATIONS:
        raise ds.ServiceError("unknown_operation", "That operation is not allowed.", 422)
    clean: dict[str, Any] = {}
    for key in ("season", "round"):
        if key in params and params[key] is not None:
            if not isinstance(params[key], int) or isinstance(params[key], bool):
                raise ds.ServiceError("invalid_parameter", f"{key} must be a whole number.", 422)
            clean[key] = params[key]
    missing = [k for k in OPERATIONS[op]["needs"] if k not in clean and k not in params]
    if missing:
        raise ds.ServiceError("missing_parameter", f"Missing: {', '.join(missing)}.", 422)
    if "season" in clean and "round" in clean:
        ds.get_event(clean["season"], clean["round"])  # 404 for unknown events
    elif "season" in clean:
        ds._validate_season(clean["season"])
    if op == "generate_prediction":
        from src.services.predictor import STAGES
        session, checkpoint = params.get("session"), params.get("checkpoint")
        if (session, checkpoint) not in STAGES:
            raise ds.ServiceError("invalid_parameter", "That prediction stage is not available.", 422)
        clean.update({"session": session, "checkpoint": checkpoint, "use_weather": bool(params.get("use_weather", False)), "trigger": "automatic" if params.get("trigger") == "automatic" else "manual"})
    return clean


# ------------------------------------------------------------------ job manager
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self) -> None:
        self._q: "queue.Queue[str]" = queue.Queue(maxsize=MAX_QUEUED)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._jobs: dict[str, dict] = {}
        self._root: Path | None = None

    # storage -------------------------------------------------------------
    def _dir(self, create: bool = False) -> Path:
        d = ds.ROOT / "data" / "jobs"
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def _save(self, job: dict) -> None:
        tmp = self._dir(create=True) / f"{job['job_id']}.tmp"
        tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
        os.replace(tmp, self._dir(create=True) / f"{job['job_id']}.json")

    def _public(self, job: dict) -> dict:
        return {k: job[k] for k in ("job_id", "op", "label", "params", "status", "created_at_utc", "started_at_utc", "finished_at_utc", "summary", "error")}

    def recover(self) -> None:
        """Jobs left 'running' by a crash cannot still be running; mark them failed."""
        for path in self._dir().glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if job.get("status") in ("queued", "running"):
                job.update(status="failed", finished_at_utc=_now(), error="This job was interrupted when the app stopped.")
                self._save(job)

    # api -----------------------------------------------------------------
    def submit(self, op: str, params: dict | None = None) -> dict:
        clean = validate_params(op, params or {})
        with self._lock:
            for job in self._jobs.values():
                if job["op"] == op and job["params"] == clean and job["status"] in ("queued", "running"):
                    return self._public(job)  # identical work already pending
            job = {
                "job_id": f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{secrets.token_hex(3)}",
                "op": op, "label": OPERATIONS[op]["label"], "params": clean, "status": "queued",
                "created_at_utc": _now(), "started_at_utc": None, "finished_at_utc": None, "summary": None, "error": None,
            }
            try:
                self._q.put_nowait(job["job_id"])
            except queue.Full as exc:
                raise ds.ServiceError("queue_full", "Too many updates are already waiting. Try again in a few minutes.", 429) from exc
            self._jobs[job["job_id"]] = job
            self._save(job)
            self._ensure_worker()
            return self._public(job)

    def get(self, job_id: str) -> dict:
        if not job_id.replace("-", "").replace("T", "").isalnum() or len(job_id) > 40:
            raise ds.ServiceError("invalid_job", "That is not a valid job ID.", 422)
        job = self._jobs.get(job_id)
        if job is None:
            path = self._dir() / f"{job_id}.json"
            if not path.exists():
                raise ds.ServiceError("job_not_found", "That job does not exist.", 404)
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ds.ServiceError("job_unreadable", "That job record is damaged.", 503) from exc
        return self._public(job)

    def list(self, limit: int = 15) -> list[dict]:
        items = []
        for path in self._dir().glob("*.json"):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        items.sort(key=lambda j: j.get("created_at_utc") or "", reverse=True)
        return [self._public(j) for j in items[: min(limit, KEEP_LISTED)]]

    def busy(self) -> bool:
        return any(j["status"] in ("queued", "running") for j in self._jobs.values())

    # worker --------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._work, name="pipeline-worker", daemon=True)
            self._thread.start()

    def _work(self) -> None:
        while True:
            try:
                job_id = self._q.get(timeout=5)
            except queue.Empty:
                with self._lock:
                    if self._q.empty():
                        self._thread = None
                        return
                continue
            job = self._jobs[job_id]
            job.update(status="running", started_at_utc=_now())
            self._save(job)
            log_path = self._dir(create=True) / f"{job_id}.log"
            try:
                summary = OPERATIONS[job["op"]]["fn"](job["params"], {"log": log_path})
                job.update(status="succeeded", summary=summary)
            except JobError as exc:
                job.update(status="failed", error=str(exc))
            except ds.ServiceError as exc:
                job.update(status="failed", error=exc.message)
            except Exception:  # noqa: BLE001
                log_path.write_text(traceback.format_exc(), encoding="utf-8")
                log.exception("Job %s failed", job_id)
                job.update(status="failed", error="This step failed unexpectedly. The details are saved in the server log.")
            job["finished_at_utc"] = _now()
            self._save(job)
            with self._lock:
                self._jobs[job_id] = job  # keep the finished record for quick lookup
                finished = [j for j in self._jobs.values() if j["status"] in ("succeeded", "failed")]
                for old in sorted(finished, key=lambda j: j["created_at_utc"])[:-100]:
                    self._jobs.pop(old["job_id"], None)


manager = JobManager()
