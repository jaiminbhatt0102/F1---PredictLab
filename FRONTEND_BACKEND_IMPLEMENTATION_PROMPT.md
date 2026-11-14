# F1 PredictLab — Frontend Completion and Backend Integration Master Prompt

You are the senior full-stack engineer taking over the existing **F1 PredictLab** repository. Do not create a separate demo or replace working code unnecessarily. First inspect the repository and its existing design, scripts, schemas, tests, and model artifacts. Then implement the frontend-to-backend integration as a production-minded local application.

## Project context

- Backend: Python, FastAPI, pandas, scikit-learn.
- Frontend: React 19, TypeScript, Vite, lucide-react.
- Current frontend files: `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/src/main.tsx`.
- Backend API scaffold: `api/main.py`.
- Data/model workflow:
  - `scripts/collect_f1_data.py`
  - `scripts/normalize_f1_data.py`
  - `scripts/build_race_dataset.py`
  - `scripts/build_weather_forecasts.py`
  - `scripts/run_weather_all_models_experiment.py`
  - `scripts/train_weather_candidates.py`
  - `scripts/predict_qualifying.py`
  - `scripts/predict_upcoming_race.py`
  - `scripts/fetch_event_weather.py`
  - `scripts/predict_weather_candidates.py`
  - `scripts/f1_predictlab.py` (interactive local master controller)
  - `src/models/train_baselines.py`
- Product specification: `PRD.md`; architecture/feature/security notes are in `docs/` and `FRONTEND_AUDIT.md`.
- Production model artifacts are under `models/`; experimental weather candidates are under `models/weather_candidates/`.
- Weather candidates are experimental and must never be silently presented as production predictions or promoted automatically by the UI.
- Never fabricate schedules, driver results, prediction probabilities, model metrics, weather readings, or prediction history.

## Phase 0 — Audit before editing

1. Read `PRD.md`, `README.md`, `FRONTEND_AUDIT.md`, `docs/ARCHITECTURE.md`, `docs/FEATURE_SPEC.md`, `docs/SECURITY.md`, the current `frontend/src/App.tsx` and `styles.css`, `api/main.py`, and the relevant scripts.
2. Inspect actual CSV headers and JSON report schemas before designing response types.
3. Run backend tests (`python -m pytest -q`) and frontend build (`cd frontend; npm ci; npm run build`) before edits. Record baseline failures; do not disguise them.
4. Confirm what the current prediction scripts actually support. The current API scaffold is intentionally incomplete: `/api/v1/status` reports readiness and `/api/v1/predictions` returns `not_ready`. Do not treat the scaffold as a functioning predictor until the service layer calls real validated code.
5. Make a short implementation plan and proceed without asking the user to re-confirm the stated requirements. Preserve the existing working visual direction and improve it rather than replacing it with a generic template.

## Product and design direction

Build a **motorsport race operations / analysis workbench**, not a generic SaaS dashboard, marketing landing page, or AI-generated template.

Visual direction:
- Graphite/near-black foundation, restrained racing red for primary actions, neutral greys, and limited green/amber status colors.
- Use compact but readable information hierarchy inspired by timing screens, engineering monitors, and race-weekend control rooms.
- Keep typography intentional and consistent. Use system fonts or already-installed dependencies; do not add remote-font dependencies without a strong reason.
- Avoid common AI-generated UI patterns: giant gradient hero cards, excessive glassmorphism, random decorative blobs, glowing borders, over-rounded cards, excessive pill badges, meaningless charts, repetitive 3-column card grids, and over-animated transitions.
- Prefer useful tables, compact data visualizations, contextual annotations, real empty states, and deliberate whitespace.
- Keep red for meaningful actions or important race context, not every border or icon.
- Use subtle, fast transitions only where they clarify state. Respect `prefers-reduced-motion`.
- Support desktop and mobile; navigation must remain usable on narrow screens.
- Keep all UI copy specific to F1 workflows and plain enough to be useful.

Accessibility:
- Semantic landmarks and headings.
- Keyboard-operable navigation, filters, dialogs and tables.
- Visible focus styles; correct labels and accessible names.
- Do not rely on color alone for status.
- Accessible chart summaries and table alternatives.
- Good contrast in both themes if light/dark theme switching is implemented.
- Loading states should announce meaningful changes where appropriate.

## Required application views

Retain the existing seven sections unless audit evidence supports a better information architecture:
1. Overview
2. Race Predictor
3. Qualifying & Sprint
4. Model Lab
5. Driver & Circuit Analysis
6. Prediction History
7. System Status

### 1. Overview
Show only values returned by the API:
- Next event / selected event, session status and event schedule when schedule data is available.
- Data freshness: last successful F1 refresh, last weather snapshot, dataset season coverage, and whether inputs are stale.
- Production model readiness and active model identifiers.
- Recent prediction snapshots, if persisted.
- A small pipeline activity/status timeline, if backend job history exists.
- A concise warning when a feature or prediction mode is experimental or unavailable.
Never invent an upcoming event or show hard-coded metrics to fill space.

### 2. Race Predictor
Build a real form with:
- Season, event/round, prediction session (`qualifying`, `sprint`, `race` where supported), and checkpoint (`pre_qualifying`, `pre_race`; `live` only if genuinely implemented).
- Show which inputs are available at the selected cutoff before enabling the action.
- Explain the cutoff contract: pre-qualifying cannot use current-event qualifying/sprint/race results; pre-race may use completed qualifying and sprint data but not race outcomes or future data.
- Show the active model, model version, dataset freshness, feature availability and warnings beside the result.
- Render driver rows sorted by the predicted order or probability. Clearly label the output type: predicted qualifying position, win probability, podium probability, expected finish only if supported by the actual model.
- Use probability formatting correctly and never imply a probability is certainty.
- Show confidence/uncertainty only if the backend supplies a valid measure; do not invent confidence intervals.
- Provide CSV download only from actual response rows.
- Offer a way to save a prediction snapshot only if the API endpoint exists.
- Handle unavailable data, stale inputs, validation errors, API errors, and model-not-ready states distinctly.

### 3. Qualifying & Sprint
- Show actual completed session results from the data service.
- Show predicted qualifying order separately from actual qualifying order.
- Clearly distinguish qualifying classification from official race starting grid; grid penalties may change it.
- Sprint inputs may be used only when the sprint session is complete and before the race cutoff.
- Do not label an inferred or historical roster as an official entry list.
- Display source timestamp and data freshness.

### 4. Model Lab
- Use real evaluation reports from `reports/` exposed through backend endpoints.
- Compare production-selected models and candidate models using chronological holdout/rolling evaluation.
- Include Brier score and log loss (lower is better), ROC-AUC where valid, and calibration information only if calculated.
- Display validation seasons, training window, target, model kind, feature list/version, evaluation timestamp, sample count, and baseline comparison.
- Explain that random row-splitting can leak temporal information; use chronological evaluation.
- Display candidate-vs-production results without overwriting or implying promotion.
- Weather candidate rows must have an explicit `EXPERIMENTAL` label and show weather-feature coverage and forecast lead-time assumptions.
- Never display fabricated scores or substitute a missing metric with zero.

### 5. Driver & Circuit Analysis
- Use real endpoint-backed data only.
- If not yet implemented, provide a clear empty state saying which backend capability is missing.
- When implemented, allow filtering by season, event, driver, constructor and circuit.
- Use prior-form features that were available at the prediction cutoff; do not leak future results into a historical analysis.
- Use tables or charts only when they answer a specific question.

### 6. Prediction History
- List saved snapshots returned by the backend.
- Each snapshot should include event, session, cutoff timestamp, generated timestamp, model ID/version, feature version, source-data version, weather snapshot ID (if used), prediction rows and status.
- Support filtering by season, event, session, model, and production/experimental type.
- Provide a detail page or expandable row and compare predictions to actual outcomes only after the race result is available.
- Keep original predictions immutable; a new prediction creates a new snapshot rather than overwriting the old one.
- If there are no saved snapshots, show a real empty state, not sample rows.

### 7. System Status
- API reachability and version.
- Data pipeline last run, result, duration and failure summary where recorded.
- Dataset path must remain server-side; frontend only sees safe metadata.
- Model availability, selected production model identifiers, experimental model availability.
- Weather source, last fetch, forecast lead time, valid time, status and staleness.
- Current supported workflow stages and missing prerequisites.
- Add a refresh button that performs a real GET request; never fake a successful status.

## Backend API contract to implement

Use Pydantic request/response schemas and version all application routes under `/api/v1`. Exact route names may be adjusted to fit the existing API, but document them and keep frontend types in sync.

Minimum endpoints:
- `GET /health`: lightweight liveness only.
- `GET /api/v1/status`: readiness, data freshness, model readiness, current dataset coverage and safe service metadata.
- `GET /api/v1/events?season=2026`: events/rounds from the collected schedule, including session timestamps/status if known.
- `GET /api/v1/events/{season}/{round}`: event detail, circuit ID and available session/data status.
- `GET /api/v1/sessions/{season}/{round}`: actual qualifying/sprint/race rows that exist.
- `POST /api/v1/predictions`: validate requested event/session/checkpoint, verify prerequisites and call the actual prediction service; return `not_ready`/4xx/503 with actionable explanation if unavailable, never mock output.
- `GET /api/v1/models`: active production model registry and available experimental candidates.
- `GET /api/v1/models/evaluations`: real model evaluation report summaries.
- `GET /api/v1/weather/{season}/{round}`: stored forecast snapshots and archive metadata; make forecast vs archive semantics explicit.
- `GET /api/v1/predictions/history`: persisted prediction snapshots with pagination/filtering.
- `GET /api/v1/predictions/history/{snapshot_id}`: one immutable prediction record.
- `POST /api/v1/pipeline/jobs`: trigger a supported local pipeline operation only if safe job management is implemented; validate an allowlisted operation enum, never accept arbitrary shell commands.
- `GET /api/v1/pipeline/jobs/{job_id}`: report job state/progress/result.
- `POST /api/v1/predictions/{snapshot_id}/evaluate`: compare an existing snapshot with actual results once results are available, if that workflow is implemented.

Response shape guidelines:
- Stable fields and typed models.
- UTC ISO-8601 timestamps.
- `status` values should be a documented enum such as `ready`, `partial`, `not_ready`, `stale`, `failed`, or `experimental`.
- Errors should include a safe machine-readable code and human-readable message.
- Do not return local absolute paths, stack traces, environment variables, secrets, or raw exception text.
- Keep `VITE_API_URL` as the only frontend API configuration; never put secrets in Vite variables.
- CORS allowlist must come from environment/config and be restrictive.
- Set request size/time limits and safe logging. Add rate limits if the deployment context requires them.
- Do not add authentication or user accounts unless required by the existing product scope.

## Architecture and integration rules

1. Keep ML, data collection, feature engineering and prediction logic in Python backend modules. The browser must never load `.joblib` models or access project files directly.
2. Create a clean service layer under `src/services/` or a similarly appropriate module. API routes should validate requests and call service functions, not duplicate training/prediction code.
3. Refactor scripts only when needed to expose reusable functions; keep their CLI entry points working.
4. Do not run expensive full-history data collection or model training during an ordinary HTTP prediction request.
5. Use a bounded background-job mechanism for manual refresh/train operations. Do not create unbounded threads or let the frontend submit arbitrary commands.
6. Keep production model artifacts separate from candidate artifacts. Candidate evaluation and promotion must be explicit, auditable and atomic. The frontend may request promotion only if a secure, validated backend workflow is deliberately added.
7. The existing `scripts/f1_predictlab.py` is the local interactive controller. Keep it usable from a terminal. Do not make the web app depend on interactive `input()` prompts. Create non-interactive service functions or a validated job API for browser-triggered operations.
8. Keep prediction checkpoint/feature availability checks on the server, not only in React.
9. Never use current event qualifying, sprint or race results when generating a pre-qualifying prediction. Never use race results to predict that same race.
10. A weather candidate is experimental. Require a suitable timestamped forecast snapshot and matching lead-time contract. A 9-day forecast is not interchangeable with a roughly 24-hour lead forecast. Historical archive data must be labelled as gridded estimate/reanalysis unless a true station observation source is verified.

## Frontend engineering requirements

- Use TypeScript types for every API request and response; avoid `any` and unsafe casts.
- Create a central typed API client in `frontend/src/api/` with base URL, timeout/abort support, safe error parsing and typed methods.
- Keep API state separate from view components. Use a small existing-ecosystem solution; do not add a large state-management dependency without need.
- Create reusable components for page headers, status indicators, data freshness, filter bars, sortable tables, empty/error/loading states, probability bars, and confirmation dialogs.
- Add sort/filter/pagination where data sets justify it; make the sort order visible.
- Handle request cancellation or stale responses when users change event/session rapidly.
- Disable duplicate submissions while a request is in progress.
- Keep URL/search params in sync with key filters where useful.
- Use actual server timestamps and format them for display with timezone context.
- Never make a UI button decorative: every visible action must work, or be clearly disabled with a reason.
- Theme toggle and model switcher are allowed only when their behavior is real. A model switcher must distinguish production from experimental models and must not imply that selecting a model promotes it.
- Add an explicit “Demo data” mode only if the product owner requests it; default must be live API data or a real empty/error state.
- Do not place a frontend-only prediction algorithm in React as a substitute for the backend.

## Data and model safety

- Inspect the real output schemas of `scripts/predict_qualifying.py`, `scripts/predict_upcoming_race.py`, `scripts/predict_weather_candidates.py` and reports before implementing response mappers.
- Keep prediction CSV/JSON outputs and API response types aligned.
- A prediction must report the selected model, feature contract, event, cutoff and timestamp.
- If a selected production model or required event input is missing, return a safe not-ready response.
- Keep weather prediction outputs in a separate experimental channel.
- The UI must never automatically promote a model based on client-side comparisons.
- Use chronological validation; require evidence that a candidate is better than the incumbent under the documented promotion policy.
- Preserve all existing artifacts and create backups before any migration or model-promotion code changes.

## Tests and acceptance criteria

Backend:
- Test each endpoint with valid, invalid, missing-data, stale-data and model-not-ready cases.
- Test that pre-qualifying requests reject current-event qualifying/sprint/race leakage.
- Test that pre-race requests reject unavailable qualifying/sprint prerequisites.
- Test that a missing model or corrupt report returns a safe error, not a traceback.
- Test CORS and schema validation.
- Test weather forecast lead-time and circuit/event matching.
- Test that production artifacts remain unchanged after candidate evaluation unless explicit promotion criteria pass.
- Test prediction-history immutability and evaluation behavior if implemented.

Frontend:
- `npm run build` must pass with no TypeScript errors.
- Test loading, empty, offline, stale, not-ready, successful and server-error states.
- Test keyboard navigation and responsive layout.
- Verify no mock values appear when the API is offline.
- Verify forms send the exact request contract and render real response rows.
- Verify CSV export contains only currently displayed/returned real prediction rows.
- Verify experimental weather results are clearly separated from production.
- Add a concise manual verification checklist to `FRONTEND_AUDIT.md`.

Final delivery:
1. Implement in the existing repository; do not answer with only a plan.
2. Summarize changed files and why.
3. List exact commands to run backend and frontend in separate terminals on Windows PowerShell.
4. Report test/build results honestly.
5. List any views still waiting for genuine data or endpoints.
6. Update README/API docs with actual contracts.
7. Do not claim complete integration unless a real end-to-end request from the UI to the API returns real data.
