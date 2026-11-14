# F1 PredictLab archive cleanup report

This is a cleaned distribution copy of the uploaded project. The original uploaded ZIP was not modified.

## Excluded generated or environment-specific content

- `.venv/`: local Python environment; recreate from `requirements.txt`.
- `frontend/node_modules/`: installed npm dependencies; recreate with `npm ci`.
- `frontend/dist/`: generated Vite build output; recreate with `npm run build`.
- `.pytest_cache/`, `.ruff_cache/`, `.vite/`, `__pycache__/`, `*.pyc`, and `frontend/tsconfig.tsbuildinfo`: generated caches/build metadata.
- `_pytest_final_check/` and `_pytest_inventory_check/`: temporary test fixture outputs, not application source.
- `data/cache/` contents other than `.gitkeep`: regenerable API response cache.
- `.env`: local environment file intentionally excluded. Keep credentials and local settings outside shared archives; use `.env.example` as the template.
- Nested copies of scripts/reports under `reports/weather_candidate_review/` and `reports/weather_integration_context/`, plus ZIP snapshots stored inside `reports/`: these are archived investigation bundles, not runtime source.
- `README_PATCH.txt`: historical patch instructions superseded by the current checked-in source tree.
- Legacy top-level non-selected model-kind artifacts (`models/target_{win,podium}_{prior_baseline,logistic_regression,random_forest}.joblib`): duplicate/obsolete copies. The current training implementation stores candidate models under `models/candidates/` and active artifacts as `*_selected.joblib`; weather experiments remain under `models/weather_candidates/`.

## Preserved

- Python source, FastAPI scaffold, React/TypeScript frontend source, docs, tests, requirements, package lock, real dataset tables, current model registry/artifacts, and top-level evaluation reports.
- The original current source files have not been rewritten or deleted by this packaging cleanup.

## Important code-review findings

1. `api/main.py` is still a scaffold: `/api/v1/predictions` returns `not_ready` and does not invoke the prediction scripts/model service.
2. The React frontend has a designed navigation/workbench, but several views explicitly wait for real API endpoints; frontend/backend integration is not complete.
3. `scripts/f1_predictlab.py` is a local interactive CLI controller. It should not be called from an HTTP request because it uses terminal prompts. For web-triggered jobs, extract reusable non-interactive service functions and use a bounded job mechanism.
4. Weather models are experimental and must remain clearly separate from production predictions.
5. The controller uses existing scripts and model training code; run the backend test suite and frontend production build after extracting this cleaned archive in the user's environment.
