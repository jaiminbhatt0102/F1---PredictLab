# Product Requirements Document — F1 PredictLab

## 1. Product vision
Build a transparent F1 analytics and prediction application that uses historical qualifying, sprint, race, driver, constructor, circuit and (where available) weather/timing data to estimate likely outcomes.

## 2. Users and jobs-to-be-done
- F1 fans: explore likely race outcomes and driver probabilities.
- Data/ML learners: compare models and understand evaluation.
- Analysts: inspect historical form and prediction-vs-result records.

## 3. MVP scope
1. Select season, Grand Prix and prediction checkpoint.
2. Inspect data availability and last successful update.
3. Predict qualifying order, sprint outcome, and Grand Prix outcome where a suitable model and inputs exist.
4. Show driver-level win/podium probabilities and expected finishing position with uncertainty where supported.
5. Compare models against a historical/Elo baseline.
6. Explain major prediction drivers using feature importance/SHAP when supported.
7. Store prediction snapshots and compare them to actual results.
8. Show honest empty, loading, stale-data, partial-data and error states.

## 4. Prediction checkpoints
- Pre-qualifying: no current-event qualifying or later-session data.
- Post-qualifying / pre-race: may use completed qualifying and sprint sessions plus information available before race start.
- Optional live-race: only use information observed up to the timestamp of the forecast.

Each prediction record must store event/session, cutoff timestamp, feature version, model version, generated timestamp, and source-data version.

## 5. Non-goals for MVP
- Guaranteed winner claims.
- Unverified live timing.
- Automatic betting advice.
- User accounts unless a concrete need is established.
- Using future session results as features for earlier predictions.

## 6. Acceptance criteria
- Data joins use stable event, season, session and driver identifiers.
- Missingness and source coverage are reported.
- Chronological backtests are repeatable and documented.
- Every model is compared against a baseline.
- Probabilities are checked for validity and calibrated where data supports it.
- API rejects invalid input and returns safe, structured errors.
- UI never presents mock values as real predictions.
- Unit, data-quality, API, leakage and frontend tests pass before release.
- A clean setup from README works on a supported environment.

## 7. Success metrics
Model metrics: log loss, Brier score, calibration, top-3 precision/recall or ranking metrics, and finishing-position error.
Product metrics: data refresh success, API reliability, meaningful empty/error states, accessible responsive behavior, and prediction history coverage.
No target performance score is promised until a baseline is measured.
