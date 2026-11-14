# Feature and data specification

All features must include a documented definition, source, availability cutoff, missingness behavior, and validation.

| Group | Candidate fields | Source / notes | Cutoff rule |
|---|---|---|---|
| Event identity | season, round, event, circuit, session type | Results API / FastF1 | Known at forecast time |
| Driver history | recent finishes, points, DNF rate, circuit history | Historical results | Prior events only |
| Driver pace | qualifying gaps, lap/sector pace, teammate-relative pace | FastF1 where available | Completed sessions only |
| Constructor | recent team results, teammate comparison, reliability | Historical results | Prior events only |
| Grid / penalties | qualifying position, grid slot, confirmed penalties | Results and official data where available | Only after published/confirmed |
| Sprint | sprint qualifying/result, sprint points | Session results | Only after completed sprint |
| Tyres | compound, stint age, pit stops, degradation proxy | FastF1 where supported | Historical or live-observed only |
| Weather | temperature, wind, precipitation / forecast | Historical weather / forecast provider | Use forecast vintage available at cutoff |
| Circuit | length, layout characteristics, historical incident rates | Circuit metadata / historical races | Avoid future-derived aggregates |
| Incidents | safety car, red flag, reliability/DNF rates | Historical results and race control where available | Past events only for pre-race |
| Regulation era | season/rule era, sprint format | Curated metadata | Must be versioned and documented |

## Target definitions
- Qualifying: final qualifying position or session ranking; separate handling for eliminated/no-time drivers.
- Sprint: official sprint finishing position and winner label.
- Grand Prix: official race finishing position and winner label.
- Podium: classified top-three finish, with DNS/DNF treatment explicitly documented.

## Missing data
- Do not replace unknown values with fabricated values.
- Add missingness indicators when justified.
- Fit imputers only on training data.
- Report coverage by season and session.
- Exclude a feature if coverage or semantics make it unreliable.

## Leakage rules
- Never use the target session's finishing result, fastest lap, pit stops, safety-car events or post-race facts for a pre-race prediction.
- Qualifying features are unavailable before qualifying.
- Sprint results are unavailable until the sprint ends.
- Live forecasts may only use observations timestamped at or before the forecast.
- Aggregate historical features must be shifted so the current event is excluded.
