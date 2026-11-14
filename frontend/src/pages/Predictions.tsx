import { useEffect, useMemo, useRef, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { api, ApiError } from '../api/client'
import type { Checkpoint, EventInfo, PredictionRequest, PredictionResponse, SessionName, SnapshotSummary } from '../api/types'
import { useFetch } from '../hooks/useFetch'
import { Link, to, useLocation } from '../router'
import { useSelection } from '../data'
import { ContextBar } from '../layout/ContextBar'
import { Banner, EmptyState, ErrorState, Loading, PageHeader } from '../components/ui'
import { PredictionBody } from '../components/PredictionView'
import { WeatherCard } from '../components/WeatherCard'
import { useToast } from '../components/toast'

interface StageDef { id: Checkpoint; session: SessionName; label: string; blurb: string }
const STAGES: StageDef[] = [
  { id: 'pre_qualifying', session: 'qualifying', label: 'Before qualifying', blurb: 'Who will be fastest in qualifying' },
  { id: 'pre_sprint', session: 'sprint', label: 'Before the sprint', blurb: 'How the sprint may finish' },
  { id: 'post_qualifying', session: 'race', label: 'After qualifying', blurb: 'Race chances once the grid is set by qualifying' },
  { id: 'pre_race', session: 'race', label: 'Before the race', blurb: 'Race chances using the starting grid' },
]

type StageState = { kind: 'ready' | 'waiting' | 'done' | 'hidden'; note: string }

export function stageState(e: EventInfo, s: StageDef, previous: EventInfo | null = null): StageState {
  const sess = e.sessions
  if (s.id === 'pre_sprint' && !e.is_sprint_weekend) return { kind: 'hidden', note: '' }
  if (sess[s.session] === 'complete') return { kind: 'done', note: 'Already happened' }
  if (previous && previous.sessions.race !== 'complete') return { kind: 'waiting', note: 'Waiting for the previous race result' }
  if (s.session === 'race') {
    if (sess.qualifying !== 'complete') return { kind: 'waiting', note: 'Waiting for qualifying' }
    if (e.is_sprint_weekend && sess.sprint !== 'complete') return { kind: 'waiting', note: 'Waiting for the sprint' }
  }
  return { kind: 'ready', note: 'Ready' }
}

function defaultStage(e: EventInfo): Checkpoint {
  if (e.sessions.race === 'complete') return 'pre_race'
  if (e.sessions.qualifying !== 'complete') return 'pre_qualifying'
  return 'post_qualifying'
}

export default function Predictions() {
  const { event, season, round, events } = useSelection()
  const params = useLocation().search
  const toast = useToast()
  const stage = (STAGES.find((s) => s.id === params.get('stage'))?.id ?? (event ? defaultStage(event) : 'pre_qualifying')) as Checkpoint
  const def = STAGES.find((s) => s.id === stage) as StageDef
  const [useWeather, setUseWeather] = useState(false)
  const [fresh, setFresh] = useState<PredictionResponse | null>(null)
  const [problem, setProblem] = useState<PredictionResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const latest = useFetch(season && round ? (s) => api.latest(season, round, s) : null, [season, round])
  const weather = useFetch(season && round ? (s) => api.weather(season, round, s) : null, [season, round])
  const wxStatus = weather.data?.forecast_snapshots[0]?.lead_time_check
  const wxOk = wxStatus?.status === 'ok'

  const previous = events.data?.events.find((e) => event && e.round === event.round - 1) ?? null
  const state = event ? stageState(event, def, previous) : null
  const effectiveWeather = useWeather && def.session === 'race' && wxOk
  const saved: SnapshotSummary | undefined = useMemo(
    () => latest.data?.items.find((i) => i.requested.checkpoint === stage && (i.kind === 'experimental') === effectiveWeather),
    [latest.data, stage, effectiveWeather],
  )
  const detail = useFetch(saved ? (s) => api.snapshot(saved.snapshot_id, s) : null, [saved?.snapshot_id])

  useEffect(() => {
    abortRef.current?.abort()
    setFresh(null); setProblem(null); setError(null); setBusy(false)
  }, [season, round, stage, effectiveWeather])
  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => { if (!wxOk) setUseWeather(false) }, [wxOk])

  const make = async () => {
    if (!event || busy || state?.kind !== 'ready') return
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    setBusy(true); setError(null); setProblem(null)
    const body: PredictionRequest = { season: event.season, round: event.round, session: def.session, checkpoint: stage, use_weather: effectiveWeather }
    try {
      const res = await api.predict(body, c.signal)
      if (c.signal.aborted) return
      if (res.status === 'ready') { setFresh(res); toast('Prediction made and saved to your history.', 'ok'); latest.reload() }
      else setProblem(res)
    } catch (e) {
      if (!c.signal.aborted) setError(e instanceof ApiError ? e : new ApiError('offline', 'unknown', 'Something went wrong.'))
    } finally { if (!c.signal.aborted) setBusy(false) }
  }

  const shown = fresh ?? (detail.data && detail.data.status === 'ready' ? detail.data : null)

  return (
    <>
      <ContextBar />
      <PageHeader title="Predictions" lead="Pick a moment in the weekend. Each prediction uses only what was known at that moment, and every one is saved so we can check it against the result." />
      <div className="stages" role="tablist" aria-label="When to predict">
        {event && STAGES.map((s) => {
          const st = stageState(event, s, previous)
          if (st.kind === 'hidden') return null
          return (
            <Link key={s.id} role="tab" aria-selected={stage === s.id} className={`stage stage-${st.kind}`} to={to('/predictions', { season, round, stage: s.id })}>
              <strong>{s.label}</strong>
              <span>{s.blurb}</span>
              <em>{st.note}</em>
            </Link>
          )
        })}
      </div>

      {!event && <EmptyState title="Choose a Grand Prix">Pick a season and Grand Prix above.</EmptyState>}

      {event && def.session === 'race' && (
        <label className={`check ${wxOk ? '' : 'off'}`}>
          <input type="checkbox" checked={effectiveWeather} disabled={!wxOk} onChange={(e) => setUseWeather(e.target.checked)} />
          <span>Also use the weather forecast (beta)
            <small>{wxOk ? 'A forecast from the day before the race is saved, so a weather version can be made. It is an experiment and is not our main prediction.' : 'Available once a forecast from the day before the race has been saved. The app does this automatically.'}</small>
          </span>
        </label>
      )}

      <div aria-live="polite">
        {state?.kind === 'ready' && (
          <div className="make">
            <button type="button" className="btn primary" onClick={() => void make()} disabled={busy} aria-busy={busy}>
              {busy ? <><LoaderCircle size={16} className="spin" aria-hidden="true" />Working</> : shown ? 'Make a fresh prediction' : 'Make this prediction'}
            </button>
            <span className="muted">{shown ? 'A fresh prediction is saved as a new entry; earlier ones are never changed.' : 'It takes a few seconds.'}</span>
          </div>
        )}
        {state?.kind === 'waiting' && <Banner tone="neutral" title={state.note}>{previous && previous.sessions.race !== 'complete' ? `We use the results of earlier races, and ${previous.race_name} hasn’t been added yet. ` : 'This prediction needs the result of an earlier session. '}It is made automatically as soon as that result arrives, and you will find it here.</Banner>}
        {state?.kind === 'done' && <Banner tone="neutral" title="This session has already happened">A new prediction now would not be a fair test. {saved ? 'Here is what we predicted at the time.' : 'No prediction was saved for it.'} <Link to={to('/history', { season: event?.season, round: event?.round })}>See how it compared</Link>.</Banner>}
        {problem && <Banner tone="warn" title="We can’t make this prediction yet">{problem.message}{problem.next_step ? ` ${problem.next_step}` : ''}</Banner>}
        {error && <ErrorState error={error} onRetry={() => void make()} />}
      </div>

      {(latest.loading || detail.loading) && !shown && <Loading label="Loading the saved prediction" />}
      {latest.error && <ErrorState error={latest.error} onRetry={latest.reload} />}
      {shown ? (
        <section className="panel" aria-labelledby="res-h"><PredictionBody res={shown} /></section>
      ) : (
        !latest.loading && !detail.loading && event && state?.kind !== 'waiting' && !busy && !problem && (
          <EmptyState title="No prediction saved for this moment yet">{state?.kind === 'ready' ? 'Use “Make this prediction”, or wait: the app makes it automatically.' : 'Nothing was saved for this session before it happened.'}</EmptyState>
        )
      )}
      <WeatherCard season={season} round={round} />
    </>
  )
}
