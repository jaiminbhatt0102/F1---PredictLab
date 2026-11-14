# F1 PredictLab — Weather Candidate Phase 2

This is the practical endpoint for the temperature-only weather experiment.

## What the results say
- Historical join passed: 3,832 training rows stayed 3,832 after the many-to-one race-weather join.
- Temperature exists for 109 races across 2022–2026.
- Across the 2023–2025 chronological folds, temperature improved mean Brier score for HistGradientBoosting for both win and podium. The 2026 forward fold is mixed for win, so the candidate remains experimental.
- The six-variable experiment is not promoted: only 2024–2025 has all six variables, giving too little history.
- Production model files are not changed.

## Copy these files into your repo
- `scripts/train_weather_candidates.py`
- `scripts/predict_weather_candidates.py`

## 1. Train isolated candidates
From repo root, with `.venv` active:
```powershell
python scripts/train_weather_candidates.py
```
Reads `data/features/race_training_weather_temperature_experimental.csv`, writes only to:
- `models/weather_candidates/`
- `reports/weather_candidate_training.json`

It trains HistGradientBoosting and RandomForest candidates for both targets, on available 2022–2026 data. HistGradientBoosting is the primary experimental candidate by pre-2026 mean Brier score; RandomForest is retained as a comparison because the 2026 win fold was mixed.

## 2. Fetch a race forecast around 24 hours before the event
Example for US GP Round 18:
```powershell
python scripts/fetch_event_weather.py forecast --season 2026 --round 18
```
Run this when the scheduled race start is about 18–30 hours away. Earlier snapshots are preserved, but this prediction script deliberately rejects them because the historical experiment uses Open-Meteo Previous Runs `previous_day1`, a 24-hour lead-time forecast value.

## 3. Generate experimental weather predictions
Make sure qualifying and race history data are refreshed/normalized first, then run:
```powershell
python scripts/predict_weather_candidates.py --season 2026 --round 18
```
Output:
`reports/weather_candidate_predictions.csv`

The script will fail safely if no matching near-race snapshot exists or if circuit IDs mismatch. It never overwrites `reports/upcoming_race_predictions.csv` or production model artifacts.

## Done / not done
**Done:** data join check, chronological experiment, isolated candidate training workflow, and a strict near-24-hour inference contract.

**Not promoted:** weather is not part of the default production predictor. Review at least several future events against the existing production prediction output before considering promotion. Weather forecasts change; the 9-day forecast snapshot is not interchangeable with the 24-hour historical feature.

## How the app works (v0.3.0)

The app follows a race weekend and keeps itself up to date.

| Moment | Uses | Predicts |
|---|---|---|
| Before qualifying | Past races only | Qualifying order |
| Before the sprint (sprint weekends) | Past races only | Sprint order |
| After qualifying (and sprint) | This weekend's qualifying and sprint results plus past races | Race win and podium chances |
| Before the race | The same, with the official starting grid when published, otherwise the qualifying order (clearly labelled) | Race win and podium chances |
| After the race | The result is added, models retrain, the actual weather is saved | Ready for the next race |

Every prediction is saved as an immutable snapshot in `data/predictions/` and compared with the real result afterwards.

### What runs automatically
`src/services/automation.py` checks the calendar every 15 minutes (inside the API process, or one check at a time via `python scripts/run_automation.py` from Windows Task Scheduler). It is data-driven: it polls for results during race week and reacts when qualifying, sprint or race data actually appears.

- Weekly: refresh the race schedule.
- Race week: save a weather forecast daily (every 3 hours the day before the race); look for new results every 2 hours.
- Within 5 days: prediction before qualifying (once). Sprint weekends: prediction before the sprint.
- When qualifying (and sprint) results appear: race prediction after qualifying; try to fetch the official grid.
- Within 30 hours of the start: race prediction before the race (new snapshot when the official grid arrives); an experimental weather version when a forecast 18 to 30 hours before the race exists.
- After the race: refresh data, retrain race, sprint and qualifying models; 26 hours later save the actual weather and retrain the experimental weather models (retried once at 6 days).

Settings (environment variables): `AUTOMATION_ENABLED` (default `1`), `AUTOMATION_INTERVAL_MIN` (default `15`), `CORS_ORIGINS`, `F1_PROJECT_ROOT` (point at another copy of the data, used by tests).

### Data sources
Results, calendar and session times come from the Jolpica (Ergast-compatible) API through `src/data/collectors.py`; the schedule also uses FastF1 (`scripts/build_f1_schedule.py`); weather comes from Open-Meteo. A starting grid can also be dropped in by hand as `data/processed/<season>_starting_grid.csv` with columns `season,round,driver_id,grid`.

### Weather, honestly
Weather forecasts are matched to races and weather models are trained from what the forecast said about 24 hours before each past race, so training matches what is available at prediction time. The actual weather is saved too. Tests on past seasons have not shown weather clearly improving predictions, so it is offered only as a labelled beta alongside the main prediction and is never promoted by the website.

## API contract (v0.3.0)

All application routes are under `/api/v1`. Errors are `{"error": {"code", "message"}}` and never contain paths or tracebacks. A prediction that cannot be made returns HTTP 200 with `status: "not_ready"`, a `code`, a plain-language `message` and nothing is saved.

| Route | Purpose |
|---|---|
| `GET /health` | Liveness |
| `GET /api/v1/status` | Readiness, data freshness, models, latest weather, capabilities, automation state |
| `GET /api/v1/events?season=` | Schedule with weekend stage, per-session state and known session times |
| `GET /api/v1/sessions/{season}/{round}` | Actual qualifying, sprint and race rows |
| `GET /api/v1/weather/{season}/{round}` | Forecast snapshots (with lead-time check) and archive |
| `POST /api/v1/predictions` | `{season, round, session, checkpoint, use_weather}`; runs the model, saves a snapshot |
| `GET /api/v1/predictions/latest/{season}/{round}` | Newest saved prediction per stage |
| `GET /api/v1/predictions/history` | Saved predictions (filter: season, round, session, kind; paged) |
| `GET /api/v1/predictions/history/{id}` | One snapshot plus its comparison with the real result when available |
| `GET /api/v1/predictions/track-record` | How saved predictions turned out |
| `GET /api/v1/analysis/season/{season}`, `/constructors/{season}`, `/circuit/{id}` | Real results |
| `GET /api/v1/automation` | What runs automatically and the last check |
| `POST /api/v1/pipeline/jobs`, `GET /api/v1/pipeline/jobs[/{id}]` | Allowlisted updates: refresh_data, fetch_weather_forecast, train_models, train_weather, post_race_update, refresh_schedule, backfill_history |
| `GET /api/v1/models`, `/models/evaluations` | Model files and training reports (not shown in the UI) |

Valid prediction stages: `qualifying/pre_qualifying`, `sprint/pre_sprint`, `race/post_qualifying`, `race/pre_race`. The server refuses a prediction for a session that has already happened, a race prediction before qualifying (and the sprint on sprint weekends), a prediction when an earlier race has no result yet, and any model that was trained on the event being predicted. Jobs accept only the operations above with validated integer parameters, run one at a time with a bounded queue, and never use a shell.

## Run it (Windows)

One command, one address. From the project folder:

```powershell
pip install -r requirements.txt     # first time only
python run_app.py
```

or double-click `start.bat`. It finds a free port (so "WinError 10013, port forbidden" cannot stop it), starts the app, waits until it is ready and opens your browser. Leave the window open while you use the app; press Ctrl+C to stop. The finished app screen is included (`frontend/dist`), so Node.js is not needed to use it.

To change the app screen itself: `cd frontend; npm ci; npm run build`, then restart. For live editing run `python run_app.py --port 8010 --no-browser` in one terminal and `cd frontend; $env:API_PORT=8010; npm run dev` in another, then open http://127.0.0.1:5173.

If you would rather not keep it running, schedule `python scripts/run_automation.py` every 15 minutes in Windows Task Scheduler.

**If a page says "not found":** you opened the engine's own address with a path that does not exist, or an old link. Open the address `run_app.py` prints, with nothing after the port number.

## How accurate is it, and how was that checked?

Predictions are tested the way they are used: each season is scored by a model trained only on earlier seasons (rolling validation over 2022 to 2024, then a 2025 holdout). `python scripts/run_feature_experiment.py` repeats the comparison and writes `reports/feature_experiment.json`.

What was tried, and what was kept:

| Idea | Result | Kept |
|---|---|---|
| Make each race's win chances add up to 100% (podium to 300%) | Models score drivers one by one and were over-confident. Fixing it improved every model type. For the production model (gradient boosting) the gain is modest: win Brier 0.0301 to 0.0285 and podium 0.0712 to 0.0683 on the 2025 holdout | Yes |
| Weight recent seasons more (each season back counts 40% less) | Better for every model type; small for the production model | Yes |
| Team pace (a constructor's average finish and qualifying position over its last 3 races) | Helped weaker models slightly; no help for the production race model or the qualifying model | Built in, and chosen automatically only if it helps on validation. Currently not selected |
| Qualifying lap-time gaps (gap to pole in %, stage reached) | **Cannot be tested yet**: the collector was not saving lap times, so every past qualifying time in your data is empty. The collector is fixed | Chosen automatically after a full refresh, only if validation improves |
| Weather (temperature) | No clear improvement | Beta only |

To give the model lap times, use **Updates, More options, Add qualifying lap times to history** once (10 to 20 minutes, needs internet). After that, every retrain tests the lap-time features and uses them only if they genuinely help.

Honest expectations: with results-only data the model has real but limited skill. The remaining large gain would come from new information the data does not contain, such as Friday practice race-pace from FastF1, reliability records and wet-race history.

## Tests

```powershell
python -m pytest -q                      # backend, 99 tests
cd frontend; npm run build               # type-checks and builds
```

Browser tests (need `pip install playwright`, `playwright install chromium`, the API and `npm run dev` running against a sandbox copy): see `tests/e2e/`.
