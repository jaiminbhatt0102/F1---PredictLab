import { api } from '../api/client'
import type { EventInfo, RaceRow, SnapshotDetail } from '../api/types'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { Link, to } from '../router'
import { ContextBar } from '../layout/ContextBar'
import { Banner, EmptyState, ErrorState, Freshness, KeyValues, Loading, Status } from '../components/ui'
import { CalendarRows, RaceHero, SessionTimeline } from '../components/race'
import { DriverStandings, TeamStandings } from '../components/standings'
import { LeadPick } from '../components/PredictionView'
import { WeatherCard } from '../components/WeatherCard'
import { formatDateTime } from '../lib/format'

function nextAction(e: EventInfo): { label: string; to: string } {
  const q = { season: e.season, round: e.round }
  switch (e.weekend_stage) {
    case 'upcoming': return { label: 'See the qualifying prediction', to: to('/predictions', { ...q, stage: 'pre_qualifying' }) }
    case 'qualifying_complete_sprint_pending': return { label: 'See the qualifying result', to: to('/results', { ...q, tab: 'qualifying' }) }
    case 'qualifying_complete': return { label: 'See the race prediction', to: to('/predictions', { ...q, stage: 'post_qualifying' }) }
    default: return { label: 'See how we did', to: to('/history', q) }
  }
}

export default function Home() {
  const { season, round, event, events, status } = useSelection()
  const drivers = useFetch(season ? (s) => api.seasonSummary(season, s) : null, [season])
  const teams = useFetch(season ? (s) => api.constructors(season, s) : null, [season])
  const latest = useFetch(season && round ? (s) => api.latest(season, round, s) : null, [season, round])
  // The most useful saved prediction for this weekend: race first, then sprint, then qualifying.
  const pick = latest.data?.items.filter((i) => i.kind === 'production').sort((a, b) => ['race', 'sprint', 'qualifying'].indexOf(a.requested.session) - ['race', 'sprint', 'qualifying'].indexOf(b.requested.session) || b.created_at_utc.localeCompare(a.created_at_utc))[0]
  const featured = useFetch<SnapshotDetail>(pick ? (s) => api.snapshot(pick.snapshot_id, s) : null, [pick?.snapshot_id])
  const done = (events.data?.events ?? []).filter((e) => e.weekend_stage === 'race_complete').slice(-3).reverse()
  const recent = useFetch(season && done.length ? async (s) => Promise.all(done.map((e) => api.sessions(e.season, e.round, s))) : null, [season, done.map((d) => d.round).join(',')])
  const upcoming = (events.data?.events ?? []).filter((e) => e.weekend_stage !== 'race_complete').slice(0, 5)
  const data = status.data?.data
  const action = event ? nextAction(event) : null
  const f = featured.data
  const lead = f && f.output_type === 'win_and_podium_probability' ? [...(f.rows as RaceRow[])].sort((a, b) => b.win_probability - a.win_probability)[0] : null

  return (
    <>
      <ContextBar />
      {events.loading && <Loading label="Loading the race schedule" />}
      {events.error && <ErrorState error={events.error} onRetry={events.reload} />}
      {!events.loading && !events.error && !event && <EmptyState title="The schedule isn’t available">No race could be found for this season. Try another season, or retry once the data has been collected.</EmptyState>}
      {event && (
        <>
          <RaceHero event={event}>
            {action && <Link to={action.to} className="btn primary">{action.label}</Link>}
            <Link to={`/races/${event.season}/${event.round}`} className="btn">Race weekend page</Link>
          </RaceHero>
          <SessionTimeline event={event} />
        </>
      )}
      {data?.stale_events.length ? (
        <Banner tone="warn" title="A result is overdue">{data.stale_events.map((e) => `Round ${e.round} (${e.race_name})`).join(', ')} should be finished but its result has not arrived. Open Updates to refresh.</Banner>
      ) : null}

      <div className="cols">
        <div>
          <section className="section" aria-labelledby="feat-h">
            <div className="section-head"><h2 id="feat-h">Featured prediction</h2><Link to={to('/predictions', { season, round })}>All predictions</Link></div>
            {(latest.loading || featured.loading) && <Loading />}
            {latest.error && <ErrorState error={latest.error} onRetry={latest.reload} />}
            {latest.data && !pick && <EmptyState title="No prediction saved for this weekend yet">Predictions are made automatically in race week, as soon as they are possible. You can also make one on the Predictions page.</EmptyState>}
            {f && (
              <div className="panel">
                <p className="muted">{f.stage?.label} · {f.output_label} · <Freshness iso={f.created_at_utc} label="made" /></p>
                {lead ? <LeadPick row={lead} season={f.requested.season} label="Most likely winner" /> : <p><strong>{f.rows[0] && 'driver_name' in f.rows[0] ? f.rows[0].driver_name : ''}</strong> is predicted fastest.</p>}
                <p className="small">A probability is an estimate, not a promise. <Link to={`/history/${f.snapshot_id}`}>Open the full prediction</Link></p>
              </div>
            )}
          </section>

          <section className="section" aria-labelledby="rec-h">
            <div className="section-head"><h2 id="rec-h">Recent results</h2><Link to={to('/results', { season, round })}>All results</Link></div>
            {recent.loading && <Loading />}
            {!recent.loading && done.length === 0 && <p className="muted">No race has finished this season yet.</p>}
            {recent.data && (
              <ul className="rows">
                {recent.data.map((s, i) => {
                  const rows = s.sessions.race.rows.slice(0, 3)
                  return (
                    <li key={done[i].round}>
                      <Link to={`/races/${done[i].season}/${done[i].round}`} className="row-link" style={{ gridTemplateColumns: '36px minmax(0,1fr) auto' }}>
                        <span className="pos">{done[i].round}</span>
                        <span className="name">{done[i].race_name}<span className="sub">{rows.map((r) => r.driver_family_name).join(', ')}</span></span>
                        <span className="pts" style={{ fontSize: '0.9rem' }}>{rows[0] ? `${rows[0].driver_family_name} won` : ''}</span>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          <section className="section" aria-labelledby="cal-h">
            <div className="section-head"><h2 id="cal-h">Coming up</h2><Link to={to('/calendar', { season })}>Full calendar</Link></div>
            {upcoming.length ? <CalendarRows events={upcoming} season={season ?? 0} currentRound={round} /> : <p className="muted">No more races on this season’s calendar.</p>}
          </section>
        </div>

        <aside aria-label="Standings and status">
          <section className="section" aria-labelledby="ds-h">
            <div className="section-head"><h2 id="ds-h">Drivers</h2><Link to={to('/drivers', { season })}>All drivers</Link></div>
            {drivers.loading && <Loading />}
            {drivers.error && <ErrorState error={drivers.error} onRetry={drivers.reload} />}
            {drivers.data && season && <DriverStandings drivers={drivers.data.drivers} season={season} limit={6} />}
            {drivers.data && <p className="small">After {drivers.data.rounds_covered} races. Race points only.</p>}
          </section>
          <section className="section" aria-labelledby="ts-h">
            <div className="section-head"><h2 id="ts-h">Teams</h2><Link to={to('/teams', { season })}>All teams</Link></div>
            {teams.loading && <Loading />}
            {teams.error && <ErrorState error={teams.error} onRetry={teams.reload} />}
            {teams.data && season && <TeamStandings teams={teams.data.constructors} season={season} limit={6} />}
          </section>
          <WeatherCard season={season} round={round} />
          <section className="panel" aria-labelledby="ready-h">
            <h2 id="ready-h">Is it ready?</h2>
            {status.loading && <Loading />}
            {status.error && <ErrorState error={status.error} onRetry={status.reload} />}
            {status.data && (
              <KeyValues items={[
                { label: 'Predictions', value: <Status tone={status.data.models.status === 'ready' ? 'ok' : 'bad'}>{status.data.models.status === 'ready' ? 'Models ready' : 'Models need training'}</Status> },
                { label: 'Race data', value: <><Freshness iso={data?.last_collection_at_utc} label="" /></> },
                { label: 'Latest race', value: data?.latest_completed_event ? `${data.latest_completed_event.race_name}` : 'None yet' },
                { label: 'Automatic updates', value: <Status tone={status.data.automation.enabled && status.data.automation.running ? 'ok' : 'warn'}>{status.data.automation.enabled ? (status.data.automation.running ? 'On' : 'Starting') : 'Off'}</Status> },
              ]} />
            )}
            <p className="small"><Link to="/updates">Open updates and status</Link>{event?.race_start_utc ? ` · Race start ${formatDateTime(event.race_start_utc)}` : ''}</p>
          </section>
        </aside>
      </div>
    </>
  )
}
