import type { ReactNode } from 'react'
import type { EventInfo, SessionName } from '../api/types'
import { Photo } from '../art/Photo'
import { TrackArt } from '../art/TrackArt'
import { Link, to } from '../router'
import { stageLabel } from '../lib/stage'
import { countdown, formatDay } from '../lib/format'
import { useNow } from '../lib/useNow'
import { Status } from './ui'

const place = (e: EventInfo) => [e.circuit_name, e.locality, e.country].filter(Boolean).join(' · ') || 'Circuit not recorded'

/** Big editorial header for one Grand Prix. Uses a stored photo if there is one, else designed artwork. */
export function RaceHero({ event, children }: { event: EventInfo; children?: ReactNode }) {
  const now = useNow()
  const left = countdown(event.race_start_utc, now)
  const alt = `${event.race_name ?? 'Grand Prix'}, round ${event.round}`
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-copy">
        <h1 id="hero-title">{event.race_name}</h1>
        <p className="hero-where">Round {event.round} · {place(event)}</p>
        <dl className="hero-meta">
          <div><dt>Race start</dt><dd>{formatDay(event.race_start_utc)}</dd></div>
          {left && <div className="countdown"><dt>Lights out in</dt><dd><strong>{left}</strong></dd></div>}
          <div><dt>Format</dt><dd>{event.is_sprint_weekend ? 'Sprint weekend' : 'Standard weekend'}</dd></div>
        </dl>
        <p><Status tone={event.weekend_stage === 'race_complete' ? 'ok' : event.weekend_stage === 'upcoming' ? 'neutral' : 'warn'}>{stageLabel(event.weekend_stage)}</Status></p>
        {children && <div className="hero-actions">{children}</div>}
      </div>
      <div className="hero-art">
        <Photo kind="hero" id={event.circuit_id} alt={alt} fallback={<TrackArt round={event.round} label={alt} />} />
      </div>
    </section>
  )
}

const NAMES: Record<SessionName, string> = { qualifying: 'Qualifying', sprint: 'Sprint', race: 'Race' }

/** Qualifying, sprint and race with their real state and (when the source has them) their start times. */
export function SessionTimeline({ event }: { event: EventInfo }) {
  const times: Record<SessionName, string | undefined> = { qualifying: event.session_times_utc.qualifying_utc, sprint: event.session_times_utc.sprint_utc, race: event.race_start_utc ?? undefined }
  return (
    <ol className="timeline" aria-label="Weekend sessions">
      {(['qualifying', 'sprint', 'race'] as SessionName[]).map((s) => {
        const state = event.sessions[s]
        return (
          <li key={s} className={`tl-step tl-${state}`}>
            <strong>{NAMES[s]}</strong>
            <span>{state === 'complete' ? 'Finished' : state === 'pending' ? 'Still to come' : 'No sprint this weekend'}</span>
            {times[s] && state !== 'not_applicable' && <time dateTime={times[s]}>{formatDay(times[s])}</time>}
          </li>
        )
      })}
    </ol>
  )
}

export function CalendarRows({ events, season, currentRound }: { events: EventInfo[]; season: number; currentRound?: number | null }) {
  return (
    <ul className="rows" aria-label="Race calendar">
      {events.map((e) => {
        const d = e.event_date ? new Date(`${e.event_date}T12:00:00`) : null
        return (
          <li key={e.round}>
            <Link to={`/races/${season}/${e.round}`} className={`cal-row ${e.round === currentRound ? 'current' : ''}`} aria-current={e.round === currentRound ? 'true' : undefined}>
              <span className="cal-date" aria-hidden="true"><strong>{d ? d.getDate() : '–'}</strong><span>{d ? d.toLocaleString(undefined, { month: 'short' }) : ''}</span></span>
              <span className="name">Round {e.round}: {e.race_name}<span className="sub">{[e.circuit_name, e.locality, e.country].filter(Boolean).join(' · ')}{e.is_sprint_weekend ? ' · Sprint weekend' : ''}</span></span>
              <Status tone={e.weekend_stage === 'race_complete' ? 'ok' : e.weekend_stage === 'upcoming' ? 'neutral' : 'warn'}>{stageLabel(e.weekend_stage)}</Status>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

export { to }
