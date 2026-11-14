import type {
  AutomationStatus, CircuitHistory, ConstructorSummary, DriverProfile, EventsResponse, HealthResponse, HistoryResponse, Job, JobOp,
  LatestResponse, PredictionRequest, PredictionResponse, SeasonSummary, SessionsResponse, SnapshotDetail, StatusResponse,
  TeamProfile, TrackRecord, WeatherResponse,
} from './types'

// Empty means "same address as this page": the API serves the app, and `npm run dev` proxies /api to it.
const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')
const TIMEOUT_MS = 15000

export type ApiErrorKind = 'offline' | 'timeout' | 'http' | 'aborted'

export class ApiError extends Error {
  kind: ApiErrorKind
  code: string
  status: number | null
  constructor(kind: ApiErrorKind, code: string, message: string, status: number | null = null) {
    super(message)
    this.kind = kind
    this.code = code
    this.status = status
  }
}

interface ErrorBody { error?: { code?: unknown; message?: unknown } }

async function request<T>(path: string, init: { method?: 'GET' | 'POST'; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; controller.abort() }, TIMEOUT_MS)
  const onAbort = () => controller.abort()
  init.signal?.addEventListener('abort', onAbort)
  try {
    const response = await fetch(`${BASE}${path}`, {
      method: init.method ?? 'GET',
      headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: controller.signal,
    })
    if (!response.ok) {
      let code = 'http_error'
      let message = 'The server could not complete the request.'
      try {
        const body = (await response.json()) as ErrorBody
        if (typeof body.error?.code === 'string') code = body.error.code
        if (typeof body.error?.message === 'string') message = body.error.message
      } catch { /* keep the generic message */ }
      throw new ApiError('http', code, message, response.status)
    }
    return (await response.json()) as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (timedOut) throw new ApiError('timeout', 'timeout', 'The backend took too long to respond.')
    if (init.signal?.aborted) throw new ApiError('aborted', 'aborted', 'Request cancelled.')
    throw new ApiError('offline', 'offline', 'Cannot reach the backend.')
  } finally {
    clearTimeout(timer)
    init.signal?.removeEventListener('abort', onAbort)
  }
}

export const api = {
  baseUrl: BASE,
  health: (signal?: AbortSignal) => request<HealthResponse>('/health', { signal }),
  status: (signal?: AbortSignal) => request<StatusResponse>('/api/v1/status', { signal }),
  events: (season: number, signal?: AbortSignal) => request<EventsResponse>(`/api/v1/events?season=${season}`, { signal }),
  sessions: (season: number, round: number, signal?: AbortSignal) => request<SessionsResponse>(`/api/v1/sessions/${season}/${round}`, { signal }),
  weather: (season: number, round: number, signal?: AbortSignal) => request<WeatherResponse>(`/api/v1/weather/${season}/${round}`, { signal }),
  predict: (body: PredictionRequest, signal?: AbortSignal) => request<PredictionResponse>('/api/v1/predictions', { method: 'POST', body, signal }),
  latest: (season: number, round: number, signal?: AbortSignal) => request<LatestResponse>(`/api/v1/predictions/latest/${season}/${round}`, { signal }),
  history: (query: { season?: number; round?: number; session?: string; kind?: string; limit?: number; offset?: number }, signal?: AbortSignal) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== '') q.set(k, String(v))
    return request<HistoryResponse>(`/api/v1/predictions/history?${q.toString()}`, { signal })
  },
  snapshot: (id: string, signal?: AbortSignal) => request<SnapshotDetail>(`/api/v1/predictions/history/${encodeURIComponent(id)}`, { signal }),
  trackRecord: (signal?: AbortSignal) => request<TrackRecord>('/api/v1/predictions/track-record', { signal }),
  seasonSummary: (season: number, signal?: AbortSignal) => request<SeasonSummary>(`/api/v1/analysis/season/${season}`, { signal }),
  constructors: (season: number, signal?: AbortSignal) => request<ConstructorSummary>(`/api/v1/analysis/constructors/${season}`, { signal }),
  driver: (season: number, code: string, signal?: AbortSignal) => request<DriverProfile>(`/api/v1/drivers/${season}/${encodeURIComponent(code)}`, { signal }),
  team: (season: number, slug: string, signal?: AbortSignal) => request<TeamProfile>(`/api/v1/teams/${season}/${encodeURIComponent(slug)}`, { signal }),
  circuit: (id: string, signal?: AbortSignal) => request<CircuitHistory>(`/api/v1/analysis/circuit/${encodeURIComponent(id)}`, { signal }),
  automation: (signal?: AbortSignal) => request<AutomationStatus>('/api/v1/automation', { signal }),
  jobs: (signal?: AbortSignal) => request<{ items: Job[]; busy: boolean }>('/api/v1/pipeline/jobs', { signal }),
  job: (id: string, signal?: AbortSignal) => request<Job>(`/api/v1/pipeline/jobs/${encodeURIComponent(id)}`, { signal }),
  startJob: (body: { op: JobOp; season?: number; round?: number }, signal?: AbortSignal) => request<Job>('/api/v1/pipeline/jobs', { method: 'POST', body, signal }),
}
