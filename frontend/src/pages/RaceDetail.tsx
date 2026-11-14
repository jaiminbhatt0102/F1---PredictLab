import { ArrowLeft, ArrowRight } from 'lucide-react'
import { api } from '../api/client'
import { useFetch } from '../hooks/useFetch'
import { Link, to } from '../router'
import { EmptyState, ErrorState, Freshness, Loading, SortableTable, Status } from '../components/ui'
import { RaceHero, SessionTimeline } from '../components/race'
import { WeatherCard } from '../components/WeatherCard'
import { resultColumns } from './Results'

export default function RaceDetail({ season, round }: { season: number; round: number }) {
  const events = useFetch((s) => api.events(season, s), [season])
  const event = events.data?.events.find((e) => e.round === round) ?? null
  const sessions = useFetch(event ? (s) => api.sessions(season, round, s) : null, [season, round, event?.round])
  const latest = useFetch(event ? (s) => api.latest(season, round, s) : null, [season, round, event?.round])
  const circuit = useFetch(event?.circuit_id ? (s) => api.circuit(event.circuit_id as string, s) : null, [event?.circuit_id])
  const prev = events.data?.events.find((e) => e.round === round - 1)
  const next = events.data?.events.find((e) => e.round === round + 1)
  const race = sessions.data?.sessions.race
  const quali = sessions.data?.sessions.qualifying

  return (
    <>
      <Link to={to('/calendar', { season })} className="back"><ArrowLeft size={16} aria-hidden="true" />Calendar</Link>
      {events.loading && <Loading label="Loading the Grand Prix" />}
      {events.error && <ErrorState error={events.error} onRetry={events.reload} />}
      {events.data && !event && <EmptyState title="That race isn’t on this season’s calendar" action={<Link className="btn" to={to('/calendar', { season })}>Back to the calendar</Link>}>Check the season and round in the address.</EmptyState>}
      {event && (
        <>
          <RaceHero event={event}>
            <Link className="btn primary" to={to('/predictions', { season, round })}>Predictions</Link>
            <Link className="btn" to={to('/results', { season, round })}>Results</Link>
          </RaceHero>
          <SessionTimeline event={event} />
          <div className="cols">
            <div>
              <section className="section" aria-labelledby="rr-h">
                <div className="section-head"><h2 id="rr-h">{race?.status === 'complete' ? 'Race result' : quali?.status === 'complete' ? 'Qualifying result' : 'Results'}</h2><Link to={to('/results', { season, round, tab: race?.status === 'complete' ? 'race' : 'qualifying' })}>Full results</Link></div>
                {sessions.loading && <Loading />}
                {sessions.error && <ErrorState error={sessions.error} onRetry={sessions.reload} />}
                {race?.status === 'complete' && <SortableTable caption="Race classification, top ten" columns={resultColumns('race', season)} rows={race.rows.slice(0, 10)} rowKey={(r) => `${r.driver_code}-${r.position}`} defaultSort={{ key: 'position', dir: 'asc' }} />}
                {race?.status !== 'complete' && quali?.status === 'complete' && <SortableTable caption="Qualifying classification, top ten" columns={resultColumns('qualifying', season)} rows={quali.rows.slice(0, 10)} rowKey={(r) => `${r.driver_code}-${r.position}`} defaultSort={{ key: 'position', dir: 'asc' }} />}
                {sessions.data && race?.status !== 'complete' && quali?.status !== 'complete' && <EmptyState title="No session has finished yet">Results appear here automatically once qualifying, the sprint or the race is over and the data has updated.</EmptyState>}
              </section>
              {circuit.data && (
                <section className="section" aria-labelledby="ch-h">
                  <div className="section-head"><h2 id="ch-h">Past winners here</h2></div>
                  <ul className="rows">
                    {circuit.data.races.slice(0, 8).map((r) => (
                      <li key={`${r.season}-${r.round}`}><Link className="row-link" to={`/races/${r.season}/${r.round}`}><span className="pos">{String(r.season).slice(2)}</span><span className="name">{r.winner}<span className="sub">{r.winner_team ?? ''} · started P{r.winner_grid ?? '–'}</span></span><span className="sub">{r.pole_sitter_won ? 'From pole' : ''}</span></Link></li>
                    ))}
                  </ul>
                  <p className="small">{circuit.data.races.filter((r) => r.pole_sitter_won).length} of {circuit.data.races.length} collected races here were won from pole position.</p>
                </section>
              )}
            </div>
            <aside aria-label="Prediction and weather">
              <section className="panel" aria-labelledby="pp-h">
                <h2 id="pp-h">Predictions for this race</h2>
                {latest.loading && <Loading />}
                {latest.data && latest.data.items.length === 0 && <p>None saved yet. They are made automatically in race week.</p>}
                {latest.data && latest.data.items.length > 0 && (
                  <ul className="plain">
                    {latest.data.items.map((i) => (
                      <li key={i.snapshot_id}><Link to={`/history/${i.snapshot_id}`}>{i.stage?.label}{i.kind === 'experimental' ? ' (weather beta)' : ''}</Link><span className="muted">{i.headline?.driver_name ?? ''}</span><Freshness iso={i.created_at_utc} label="" /></li>
                    ))}
                  </ul>
                )}
                <p className="small"><Status tone="neutral">Estimates</Status> Predictions stay separate from the results shown on this page.</p>
              </section>
              <WeatherCard season={season} round={round} />
            </aside>
          </div>
          <nav className="page-actions" aria-label="Other races">
            {prev && <Link className="btn" to={`/races/${season}/${prev.round}`}><ArrowLeft size={15} aria-hidden="true" />{prev.race_name}</Link>}
            {next && <Link className="btn" to={`/races/${season}/${next.round}`}>{next.race_name}<ArrowRight size={15} aria-hidden="true" /></Link>}
          </nav>
        </>
      )}
    </>
  )
}
