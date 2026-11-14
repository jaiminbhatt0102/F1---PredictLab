import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, CircleDashed, LoaderCircle, XCircle } from 'lucide-react'
import { api, ApiError } from '../api/client'
import type { Job, JobOp } from '../api/types'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { Banner, ConfirmDialog, Disclosure, ErrorState, Freshness, KeyValues, Loading, PageHeader, Status, type Tone } from '../components/ui'
import { useToast } from '../components/toast'
import { formatDateTime } from '../lib/format'

const MODEL_NAMES: Record<string, string> = { target_win: 'Race win chances', target_podium: 'Race podium chances', qualifying_position: 'Qualifying order', sprint_position: 'Sprint order' }

function JobIcon({ status }: { status: Job['status'] }) {
  if (status === 'succeeded') return <CheckCircle2 size={16} className="ok" aria-hidden="true" />
  if (status === 'failed') return <XCircle size={16} className="bad" aria-hidden="true" />
  if (status === 'running') return <LoaderCircle size={16} className="spin" aria-hidden="true" />
  return <CircleDashed size={16} aria-hidden="true" />
}
const JOB_WORD: Record<Job['status'], string> = { queued: 'Waiting its turn', running: 'Working', succeeded: 'Done', failed: 'Didn’t work' }

export default function Updates() {
  const toast = useToast()
  const { status, event } = useSelection()
  const automation = useFetch((s) => api.automation(s), [])
  const jobs = useFetch((s) => api.jobs(s), [])
  const [confirm, setConfirm] = useState<JobOp | null>(null)
  const [starting, setStarting] = useState(false)
  const seen = useRef<Record<string, Job['status']>>({})

  // Poll while something is queued or running; announce each job once when it finishes.
  const busy = jobs.data?.busy ?? false
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => jobs.reload(), 3000)
    return () => window.clearInterval(t)
  }, [busy, jobs])
  useEffect(() => {
    for (const j of jobs.data?.items ?? []) {
      const before = seen.current[j.job_id]
      seen.current[j.job_id] = j.status
      if (before && before !== j.status && (j.status === 'succeeded' || j.status === 'failed')) {
        toast(j.status === 'succeeded' ? `${j.label}: done.` : `${j.label}: ${j.error ?? 'did not work.'}`, j.status === 'succeeded' ? 'ok' : 'bad')
        if (j.status === 'succeeded') { status.reload(); automation.reload() }
      }
    }
  }, [jobs.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = async (op: JobOp) => {
    if (starting) return
    setStarting(true); setConfirm(null)
    try {
      const needsEvent = op === 'fetch_weather_forecast'
      const job = await api.startJob({ op, ...(needsEvent && event ? { season: event.season, round: event.round } : {}) })
      seen.current[job.job_id] = job.status
      toast(`${job.label}: started.`, 'neutral')
      jobs.reload()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'That could not be started.', 'bad')
    } finally { setStarting(false) }
  }

  const a = automation.data
  const s = status.data
  const modelTone = (ok: boolean): Tone => (ok ? 'ok' : 'bad')
  return (
    <>
      <PageHeader title="Updates" lead="The app keeps itself up to date. Here is what it is doing, and how to do it yourself." />
      {status.error && <ErrorState error={status.error} onRetry={status.reload} />}

      <section className="panel" aria-labelledby="auto-h">
        <h2 id="auto-h">Automatic updates</h2>
        {automation.loading && !a && <Loading />}
        {automation.error && <ErrorState error={automation.error} onRetry={automation.reload} />}
        {a && (
          <>
            <p><Status tone={a.enabled && a.running ? 'ok' : 'warn'}>{a.enabled ? (a.running ? `On. Checks every ${a.check_every_minutes} minutes` : 'Starting up') : 'Switched off'}</Status></p>
            {!a.enabled && <Banner tone="warn" title="Automatic updates are off">Set AUTOMATION_ENABLED=1 and restart the backend, or run scripts/run_automation.py from Windows Task Scheduler. You can still update by hand below.</Banner>}
            {a.last_problem && <Banner tone="warn" title="The last automatic check hit a problem">{a.last_problem}</Banner>}
            {a.last_check ? (
              <>
                <p className="muted">Last check: <Freshness iso={a.last_check.at_utc} label="" />{a.last_check.actions.length === 0 ? '. Nothing needed doing.' : '.'}</p>
                {a.last_check.actions.length > 0 && (
                  <ul className="plain">
                    {a.last_check.actions.map((x, i) => (
                      <li key={`${x.op}-${i}`}><span>{x.reason}</span><Status tone={x.status === 'succeeded' ? 'ok' : 'warn'}>{x.status === 'succeeded' ? 'Done' : x.error ?? 'Didn’t work'}</Status></li>
                    ))}
                  </ul>
                )}
              </>
            ) : <p className="muted">It hasn’t run a check yet. The first one happens a short while after the backend starts.</p>}
            <Disclosure summary="What happens automatically, and when">
              <ul className="steps">{a.steps.map((st) => <li key={st.label}><strong>{st.label}.</strong> {st.when}</li>)}</ul>
            </Disclosure>
          </>
        )}
      </section>

      <section className="panel" aria-labelledby="now-h">
        <h2 id="now-h">Update now</h2>
        <p className="muted">You normally don’t need these. Use them if you want fresh data right away.</p>
        <div className="actions">
          <button type="button" className="btn" disabled={starting || busy} onClick={() => void start('refresh_data')}>Update race results</button>
          <button type="button" className="btn" disabled={starting || busy || !event} onClick={() => void start('fetch_weather_forecast')} title={event ? undefined : 'Choose a Grand Prix first'}>Get the weather forecast{event ? ` for ${event.race_name}` : ''}</button>
          <button type="button" className="btn" disabled={starting || busy} onClick={() => setConfirm('train_models')}>Retrain the prediction models</button>
        </div>
        {busy && <p className="muted" role="status">Another update is running. Buttons come back when it finishes.</p>}
        <Disclosure summary="More options">
          <div className="actions">
            <button type="button" className="btn" disabled={starting || busy} onClick={() => void start('refresh_schedule')}>Check the race schedule</button>
            <button type="button" className="btn" disabled={starting || busy} onClick={() => setConfirm('train_weather')}>Retrain the weather models (beta)</button>
            <button type="button" className="btn" disabled={starting || busy} onClick={() => setConfirm('backfill_history')}>Add qualifying lap times to history</button>
          </div>
        </Disclosure>
        <h3>Recent updates</h3>
        {jobs.loading && !jobs.data && <Loading />}
        {jobs.error && <ErrorState error={jobs.error} onRetry={jobs.reload} />}
        {jobs.data && jobs.data.items.length === 0 && <p className="muted">Nothing has run yet.</p>}
        {jobs.data && jobs.data.items.length > 0 && (
          <ul className="plain" aria-live="polite">
            {jobs.data.items.map((j) => (
              <li key={j.job_id}>
                <span className="job"><JobIcon status={j.status} /><strong>{j.label}</strong></span>
                <span className="muted">{JOB_WORD[j.status]}{j.status === 'failed' && j.error ? `: ${j.error}` : j.summary?.message ? `: ${j.summary.message}` : ''}</span>
                <time className="muted" dateTime={j.created_at_utc}>{formatDateTime(j.created_at_utc)}</time>
              </li>
            ))}
          </ul>
        )}
      </section>

      {s && (
        <section className="panel" aria-labelledby="state-h">
          <h2 id="state-h">What the app has right now</h2>
          <KeyValues items={[
            { label: 'Race data', value: <><Status tone={s.data.status === 'ready' ? 'ok' : 'warn'}>{s.data.status === 'ready' ? 'Up to date' : s.data.status === 'stale' ? 'A result is overdue' : 'Not ready'}</Status> <Freshness iso={s.data.last_collection_at_utc} label="refreshed" /></> },
            { label: 'Latest race included', value: s.data.latest_completed_event ? `${s.data.latest_completed_event.race_name} (round ${s.data.latest_completed_event.round})` : 'None yet' },
            { label: 'Seasons covered', value: s.data.seasons.length ? `${s.data.seasons[0]} to ${s.data.seasons[s.data.seasons.length - 1]}` : 'None' },
            { label: 'Latest weather forecast', value: s.weather.latest_snapshot ? <>{s.weather.latest_snapshot.race_name} <Freshness iso={s.weather.latest_snapshot.fetched_at_utc} label="saved" /></> : 'None saved yet' },
          ]} />
          <h3>Prediction models</h3>
          <ul className="plain">
            {s.models.production.map((m) => (
              <li key={m.id}><span>{MODEL_NAMES[m.target] ?? m.target}</span><Status tone={modelTone(m.artifact_available)}>{m.artifact_available ? 'Ready' : 'Missing. Retrain the models.'}</Status></li>
            ))}
          </ul>
          <p className="small">Backend {s.service.version}. {s.models.experimental_count} experimental weather models are available for the beta version.</p>
        </section>
      )}

      <ConfirmDialog
        open={confirm !== null}
        title={confirm === 'train_weather' ? 'Retrain the weather models?' : confirm === 'backfill_history' ? 'Re-download all past seasons?' : 'Retrain the prediction models?'}
        confirmLabel={confirm === 'backfill_history' ? 'Yes, re-download' : 'Yes, retrain'}
        onConfirm={() => confirm && void start(confirm)}
        onCancel={() => setConfirm(null)}
      >
        {confirm === 'backfill_history'
          ? <p>This downloads every past season again so qualifying lap times are included, then retrains the models. It needs the internet and can take 10 to 20 minutes. You only need to do it once. If the lap times don’t improve the predictions, the models simply keep working as before. Predictions you already saved are never changed.</p>
          : <p>This teaches the models again using all the data the app has. It takes a few minutes, and the new models replace the current ones when it finishes. Predictions you already saved are never changed.</p>}
      </ConfirmDialog>
    </>
  )
}
