"""F1 PredictLab API.

Thin HTTP layer: validates requests and calls src.services, which read real pipeline
outputs, run inference with trained models, and manage allowlisted pipeline jobs.
It never returns mock predictions, local paths or tracebacks.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from src.services import automation, pipeline, predictor, snapshots
from src.services import data_service as svc

VERSION = "0.3.0"
MAX_BODY_BYTES = 4096
POSTS_PER_MINUTE = 40
log = logging.getLogger("f1_predictlab.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    started = automation.scheduler.start()
    log.info("Automation %s", "started" if started else "not started")
    yield
    automation.scheduler.stop()


app = FastAPI(
    title="F1 PredictLab API",
    version=VERSION,
    description="Leakage-aware F1 prediction API with automated data, weather and model updates.",
    lifespan=lifespan,
)

_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


_post_log: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def guard(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return _error(413, "request_too_large", "The request is too large.")
    if request.method == "POST":
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = _post_log[client]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= POSTS_PER_MINUTE:
            return _error(429, "rate_limited", "Too many requests. Please wait a moment.")
        window.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    path = request.url.path
    if path.startswith("/api/") or path == "/health":
        response.headers["Cache-Control"] = "no-store"
    elif path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-cache"  # always pick up a newly built app
    return response


@app.exception_handler(svc.ServiceError)
async def service_error_handler(_: Request, exc: svc.ServiceError) -> JSONResponse:
    return _error(exc.http_status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [".".join(str(p) for p in e.get("loc", ())[1:]) or "request" for e in exc.errors()]
    return _error(422, "invalid_request", "Some request values are not valid.", fields=fields)


@app.exception_handler(Exception)
async def unexpected_handler(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error", exc_info=exc)
    return _error(500, "internal_error", "Something went wrong on the server. Check the backend terminal for details.")


class PredictionRequest(BaseModel):
    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    session: Literal["qualifying", "sprint", "race"]
    checkpoint: Literal["pre_qualifying", "pre_sprint", "post_qualifying", "pre_race"]
    use_weather: bool = False


class JobRequest(BaseModel):
    op: Literal["refresh_data", "fetch_weather_forecast", "train_models", "train_weather", "post_race_update", "refresh_schedule", "backfill_history"]
    season: int | None = Field(default=None, ge=1950, le=2100)
    round: int | None = Field(default=None, ge=1, le=100)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "f1-predictlab-api", "version": VERSION}


@app.get("/api/v1/status")
def status() -> dict:
    out = svc.get_status(VERSION)
    out["automation"] = {"enabled": automation.scheduler.enabled(), "running": automation.scheduler.running()}
    return out


@app.get("/api/v1/events")
def events(season: int) -> dict:
    return svc.list_events(season)


@app.get("/api/v1/events/{season}/{round_no}")
def event(season: int, round_no: int) -> dict:
    return svc.get_event(season, round_no)


@app.get("/api/v1/sessions/{season}/{round_no}")
def sessions(season: int, round_no: int) -> dict:
    return svc.get_sessions(season, round_no)


@app.get("/api/v1/weather/{season}/{round_no}")
def weather(season: int, round_no: int) -> dict:
    return svc.get_weather(season, round_no)


@app.post("/api/v1/predictions")
def create_prediction(request: PredictionRequest) -> dict:
    return predictor.generate(request.season, request.round, request.session, request.checkpoint, request.use_weather)


@app.get("/api/v1/predictions/history")
def history(season: int | None = None, round: int | None = None, session: Literal["qualifying", "sprint", "race"] | None = None,
            kind: Literal["production", "experimental"] | None = None, limit: int = 30, offset: int = 0) -> dict:
    return snapshots.list_snapshots(season, round, session, kind, max(1, min(limit, 100)), max(0, offset))


@app.get("/api/v1/predictions/history/{snapshot_id}")
def history_detail(snapshot_id: str) -> dict[str, Any]:
    snap = snapshots.get(snapshot_id)
    return {**snap, "comparison": snapshots.compare_with_results(snap)}


@app.get("/api/v1/predictions/track-record")
def track_record() -> dict:
    return snapshots.track_record()


@app.get("/api/v1/predictions/latest/{season}/{round_no}")
def latest(season: int, round_no: int) -> dict:
    """Newest saved prediction for each stage of one Grand Prix."""
    svc.get_event(season, round_no)
    out = []
    for (session, checkpoint) in predictor.STAGES:
        for experimental in (False, True):
            item = snapshots.latest_for(season, round_no, session, checkpoint, experimental)
            if item:
                out.append(item)
    return {"season": season, "round": round_no, "items": out}


@app.get("/api/v1/models")
def models() -> dict:
    return svc.get_models()


@app.get("/api/v1/models/evaluations")
def evaluations() -> dict:
    return svc.get_evaluations()


@app.get("/api/v1/analysis/season/{season}")
def season_analysis(season: int) -> dict:
    return svc.season_summary(season)


@app.get("/api/v1/analysis/constructors/{season}")
def constructors(season: int) -> dict:
    return svc.constructor_summary(season)


@app.get("/api/v1/drivers/{season}/{code}")
def driver(season: int, code: str) -> dict:
    return svc.driver_profile(season, code)


@app.get("/api/v1/teams/{season}/{slug}")
def team(season: int, slug: str) -> dict:
    return svc.team_profile(season, slug)


@app.get("/api/v1/analysis/circuit/{circuit_id}")
def circuit(circuit_id: str) -> dict:
    return svc.circuit_history(circuit_id)


@app.get("/api/v1/automation")
def automation_status() -> dict:
    return automation.describe()


@app.post("/api/v1/pipeline/jobs")
def start_job(request: JobRequest) -> dict:
    params = {k: v for k, v in (("season", request.season), ("round", request.round)) if v is not None}
    return pipeline.manager.submit(request.op, params)


@app.get("/api/v1/pipeline/jobs")
def list_jobs(limit: int = 15) -> dict:
    return {"items": pipeline.manager.list(max(1, min(limit, 40))), "busy": pipeline.manager.busy()}


@app.get("/api/v1/pipeline/jobs/{job_id}")
def job(job_id: str) -> dict:
    return pipeline.manager.get(job_id)


# ---------------------------------------------------------------- the app screen
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


class AppFiles(StaticFiles):
    """Serves the built frontend. Unknown non-API paths get the app, so links and refreshes never 404."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith(("api/", "health")) and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise


if (DIST / "index.html").exists():
    app.mount("/", AppFiles(directory=DIST, html=True), name="app")
else:
    @app.get("/", include_in_schema=False)
    def not_built() -> HTMLResponse:
        return HTMLResponse(
            "<h1>F1 PredictLab</h1><p>The API is running, but the app screen has not been built yet.</p>"
            "<p>Run <code>cd frontend</code>, <code>npm ci</code>, <code>npm run build</code>, then restart. "
            "Or use <code>npm run dev</code> and open http://127.0.0.1:5173.</p>"
        )
