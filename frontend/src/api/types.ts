// Types mirror the FastAPI responses in api/main.py and src/services.
export type Stage = 'upcoming' | 'qualifying_complete_sprint_pending' | 'qualifying_complete' | 'race_complete'
export type SessionState = 'complete' | 'pending' | 'not_applicable'
export type SessionName = 'qualifying' | 'sprint' | 'race'
export type Checkpoint = 'pre_qualifying' | 'pre_sprint' | 'post_qualifying' | 'pre_race'
export type ServiceStatus = 'ready' | 'partial' | 'not_ready' | 'stale'

export interface EventInfo {
  season: number
  round: number
  race_name: string | null
  country: string | null
  locality: string | null
  circuit_id: string | null
  circuit_name: string | null
  event_date: string | null
  race_start_utc: string | null
  session_times_utc: Partial<Record<'first_practice_utc' | 'sprint_qualifying_utc' | 'sprint_utc' | 'qualifying_utc', string>>
  event_format: string | null
  is_sprint_weekend: boolean
  weekend_stage: Stage
  sessions: Record<SessionName, SessionState>
}
export interface EventsResponse {
  season: number
  generated_at_utc: string
  schedule_updated_at_utc: string | null
  default_round: number | null
  events: EventInfo[]
}

export interface WeatherCheck { status: 'ok' | 'too_early' | 'too_late' | 'unknown'; message: string }
export interface WeatherRow {
  kind: string
  fetched_at_utc: string | null
  weather_valid_time_utc: string | null
  forecast_lead_hours: number | null
  weather_source: string | null
  api_status: string | null
  temperature_c: number | null
  relative_humidity_pct: number | null
  precipitation_mm: number | null
  cloud_cover_pct: number | null
  wind_speed_kmh: number | null
  lead_time_check?: WeatherCheck
}
export interface WeatherResponse {
  event: EventInfo
  contract: { min_lead_hours: number; max_lead_hours: number }
  forecast_snapshots: WeatherRow[]
  historical_archive: WeatherRow[]
}

export interface ModelInfo { id: string; target: string; model_kind: string | null; status: 'production' | 'candidate' | 'experimental'; artifact_available: boolean; artifact_updated_at_utc: string | null }

export interface StatusResponse {
  status: ServiceStatus
  service: { name: string; version: string }
  generated_at_utc: string
  data: {
    status: ServiceStatus
    seasons: number[]
    coverage: { season: number; races_scheduled: number; races_with_results: number }[]
    latest_completed_event: { season: number; round: number; race_name: string | null } | null
    training_rows: number | null
    training_table_updated_at_utc: string | null
    last_collection_at_utc: string | null
    stale_events: { season: number; round: number; race_name: string | null }[]
  }
  models: { status: ServiceStatus; production: ModelInfo[]; experimental_count: number }
  weather: { status: ServiceStatus; latest_snapshot: (WeatherRow & { season: number; round: number; race_name: string | null }) | null }
  capabilities: Record<string, boolean>
  automation: { enabled: boolean; running: boolean }
}

export interface SessionRow {
  position: number | null
  driver_code: string | null
  driver_given_name: string | null
  driver_family_name: string | null
  constructor_name: string | null
  q1?: string | null
  q2?: string | null
  q3?: string | null
  grid?: number | null
  points?: number | null
  status?: string | null
  time?: string | null
}
export interface SessionBlock { status: SessionState; rows: SessionRow[]; source_updated_at_utc: string | null }
export interface SessionsResponse { event: EventInfo; generated_at_utc: string; sessions: Record<SessionName, SessionBlock> }

export interface PredictionRequest { season: number; round: number; session: SessionName; checkpoint: Checkpoint; use_weather: boolean }
export interface OrderRow { predicted_order: number; driver_id: string; driver_code: string | null; driver_name: string; constructor_name: string | null; predicted_position: number | null }
export interface RaceRow {
  driver_id: string
  driver_code: string | null
  driver_name: string
  constructor_name: string | null
  grid: number | null
  qualifying_position: number | null
  sprint_position: number | null
  win_probability: number
  win_rank: number
  podium_probability: number
  podium_rank: number
}
export interface WeatherContext {
  available: boolean
  captured_at_utc?: string | null
  valid_time_utc?: string | null
  lead_hours?: number | null
  temperature_c?: number | null
  rain_mm?: number | null
  wind_kmh?: number | null
  humidity_pct?: number | null
  lead_time_check?: WeatherCheck
}
export interface InputAvailability { key: string; label: string; state: string; detail?: string }
export interface PredictionResponse {
  status: 'ready' | 'not_ready'
  code: string | null
  message: string | null
  next_step?: string | null
  snapshot_id?: string
  saved?: boolean
  kind?: 'production' | 'experimental'
  created_at_utc?: string
  trigger?: 'manual' | 'automatic'
  requested: { season: number; round: number; session: SessionName; checkpoint: Checkpoint; use_weather: boolean }
  event: EventInfo | null
  event_name?: string
  stage: { checkpoint: Checkpoint; label: string; uses: string } | null
  output_type?: 'predicted_qualifying_position' | 'predicted_sprint_position' | 'win_and_podium_probability'
  output_label?: string
  model?: Record<string, string | null | undefined>
  inputs?: { grid_source?: 'official_grid' | 'qualifying_order'; weather?: WeatherContext; data_version?: { dataset_updated_at_utc: string | null; training_rows: number | null; latest_completed_event: { season: number; round: number; race_name: string | null } | null } }
  input_availability: InputAvailability[]
  warnings: string[]
  rows: (OrderRow | RaceRow)[]
}

export interface SnapshotSummary {
  snapshot_id: string
  created_at_utc: string
  trigger: 'manual' | 'automatic'
  kind: 'production' | 'experimental'
  requested: PredictionResponse['requested']
  event_name: string
  stage: { checkpoint: Checkpoint; label: string } | null
  output_type: PredictionResponse['output_type']
  headline?: { driver_name: string | null; win_probability: number | null }
}
export interface HistoryResponse { total: number; limit: number; offset: number; items: SnapshotSummary[] }
export interface Comparison {
  kind: SessionName
  headline: {
    predicted_winner?: string | null
    actual_winner?: string | null
    winner_correct?: boolean
    podium_hits?: number
    podium_picks?: number
    average_places_off?: number | null
    exact_matches?: number
    drivers_compared?: number
    top3_hits?: number
  }
  rows: { driver_code: string | null; driver_name: string; predicted_rank: number; actual_position: number | null; places_off?: number | null }[]
}
export interface SnapshotDetail extends PredictionResponse { comparison: Comparison | null }
export interface LatestResponse { season: number; round: number; items: SnapshotSummary[] }
export interface TrackRecord {
  race: { compared: number; winner_correct: number; podium_hits: number; podium_picks: number }
  qualifying: { compared: number; average_places_off: number | null; exact_matches: number; drivers_compared: number }
  sprint: { compared: number; average_places_off: number | null; exact_matches: number; drivers_compared: number }
}

export interface SeasonDriver { driver_id: string; driver_code: string | null; driver_name: string; constructor_name: string | null; races: number; points: number; wins: number; podiums: number; average_finish: number | null; average_grid: number | null }
export interface SeasonSummary { season: number; source_updated_at_utc: string | null; rounds_covered: number; drivers: SeasonDriver[] }
export interface ConstructorSummary { season: number; constructors: { constructor_name: string; points: number; wins: number; podiums: number; best_finish: number | null }[] }
export interface CircuitHistory { circuit_id: string; circuit_name: string | null; races: { season: number; round: number; race_name: string | null; winner: string; winner_team: string | null; winner_grid: number | null; podium: string[]; pole_sitter_won: boolean }[] }

export interface Job {
  job_id: string
  op: string
  label: string
  params: Record<string, number | string | boolean>
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  created_at_utc: string
  started_at_utc: string | null
  finished_at_utc: string | null
  summary: { message?: string } | null
  error: string | null
}
export interface AutomationStatus {
  enabled: boolean
  running: boolean
  check_every_minutes: number
  last_check: { at_utc: string; note: string | null; actions: { op: string; reason: string; status: string; error: string | null }[] } | null
  last_problem: string | null
  steps: { label: string; when: string }[]
  recent_jobs: Job[]
  busy: boolean
}
export type JobOp = 'refresh_data' | 'fetch_weather_forecast' | 'train_models' | 'train_weather' | 'post_race_update' | 'refresh_schedule' | 'backfill_history'
export interface HealthResponse { status: string; service: string; version: string }

export interface DriverProfile {
  season: number
  generated_at_utc: string
  source_updated_at_utc: string | null
  driver: { code: string; driver_id: string; name: string; constructor_name: string | null; team_slug: string }
  standing: { rank: number | null; points: number | null; wins: number | null; podiums: number | null; races: number | null; average_finish: number | null; average_grid: number | null; drivers_ranked: number }
  seasons_with_data: number[]
  results: { round: number; race_name: string | null; circuit_id: string | null; constructor_name: string | null; grid: number | null; position: number | null; points: number | null; status: string | null; qualifying_position: number | null; sprint_position: number | null; sprint_points: number | null }[]
}
export interface TeamProfile {
  season: number
  generated_at_utc: string
  source_updated_at_utc: string | null
  team: { name: string; slug: string }
  standing: { rank: number | null; points: number | null; wins: number | null; podiums: number | null; best_finish: number | null; teams_ranked: number }
  drivers: { driver_code: string; name: string; points: number; wins: number; podiums: number; races: number }[]
  rounds: { round: number; race_name: string | null; points: number; best_finish: number | null; drivers: { driver_code: string | null; position: number | null; grid: number | null; points: number | null }[] }[]
}
