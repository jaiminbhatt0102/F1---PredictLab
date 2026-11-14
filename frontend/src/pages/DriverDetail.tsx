import { api } from '../api/client'
import type { DriverProfile, RaceRow } from '../api/types'
import { Portrait } from '../art/Photo'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { Link, navigate, to, useLocation } from '../router'
import { ArrowLeft } from 'lucide-react'
import { EmptyState, ErrorState, Field, Freshness, Loading, PositionTile, SortableTable, type Column } from '../components/ui'
import { formatNumber, formatPercent } from '../lib/format'
import { initials, teamColour } from '../team'

type Result = DriverProfile['results'][number]

export default function DriverDetail({ code }: { code: string }) {
  const loc = useLocation()
  const { seasons, season: selSeason, round, event } = useSelection()
  const season = Number(loc.search.get('season')) || selSeason
  const data = useFetch(season ? (s) => api.driver(season, code, s) : null, [season, code])
  const latest = useFetch(selSeason && round && season === selSeason ? (s) => api.latest(selSeason, round, s) : null, [selSeason, round, season])
  const pick = latest.data?.items.find((i) => i.requested.session === 'race' && i.kind === 'production')
  const snap = useFetch(pick ? (s) => api.snapshot(pick.snapshot_id, s) : null, [pick?.snapshot_id])
  const mine = snap.data?.rows.find((r) => 'win_probability' in r && (r as RaceRow).driver_code === code) as RaceRow | undefined
  const d = data.data
  const tint = teamColour(d?.driver.constructor_name)
  const cols: Column<Result>[] = [
    { key: 'round', header: 'Round', render: (r) => <PositionTile value={r.round} />, sortValue: (r) => r.round },
    { key: 'race', header: 'Grand Prix', render: (r) => <Link to={`/races/${season}/${r.round}`}>{r.race_name}</Link>, sortValue: (r) => r.race_name },
    { key: 'q', header: 'Qualified', align: 'right', priority: 'low', render: (r) => r.qualifying_position ?? '–', sortValue: (r) => r.qualifying_position },
    { key: 'grid', header: 'Grid', align: 'right', priority: 'low', render: (r) => r.grid ?? '–', sortValue: (r) => r.grid },
    { key: 'pos', header: 'Finish', align: 'right', render: (r) => r.position ?? '–', sortValue: (r) => r.position },
    { key: 'pts', header: 'Pts', align: 'right', render: (r) => r.points ?? '–', sortValue: (r) => r.points },
    { key: 'sprint', header: 'Sprint', align: 'right', priority: 'low', render: (r) => (r.sprint_position ? `P${r.sprint_position}` : '–'), sortValue: (r) => r.sprint_position },
    { key: 'status', header: 'Status', priority: 'low', render: (r) => r.status ?? '–' },
  ]
  return (
    <>
      <Link to={to('/drivers', { season })} className="back"><ArrowLeft size={16} aria-hidden="true" />All drivers</Link>
      {data.loading && <Loading label="Loading the driver" />}
      {data.error && (data.error.status === 404
        ? <EmptyState title="No races for this driver in this season" action={<Link className="btn" to={to('/drivers', { season })}>Back to drivers</Link>}>{data.error.message} Try another season.</EmptyState>
        : <ErrorState error={data.error} onRetry={data.reload} />)}
      {d && season && (
        <>
          <section className="profile-head" aria-labelledby="drv-h">
            <Portrait kind="drivers" id={d.driver.code} alt={`${d.driver.name}, ${d.driver.constructor_name ?? ''}`} mono={initials(d.driver.name)} tint={tint} />
            <div className="profile-copy">
              <div>
                <h1 id="drv-h">{d.driver.name}</h1>
                <p className="hero-where"><Link className="team-chip" style={{ ['--tint' as string]: tint }} to={`/teams/${d.driver.team_slug}?season=${season}`}><i aria-hidden="true" />{d.driver.constructor_name}</Link> · {d.driver.code} · {season} season</p>
              </div>
              <div className="stats">
                <div className="stat"><strong>{d.standing.rank ? `P${d.standing.rank}` : '–'}</strong><span>Standing</span></div>
                <div className="stat"><strong>{d.standing.points ?? '–'}</strong><span>Points</span></div>
                <div className="stat"><strong>{d.standing.wins ?? '–'}</strong><span>Wins</span></div>
                <div className="stat"><strong>{d.standing.podiums ?? '–'}</strong><span>Podiums</span></div>
                <div className="stat"><strong>{d.standing.races ?? '–'}</strong><span>Races</span></div>
                <div className="stat"><strong>{formatNumber(d.standing.average_finish, 1)}</strong><span>Avg finish</span></div>
                <div className="stat"><strong>{formatNumber(d.standing.average_grid, 1)}</strong><span>Avg grid</span></div>
              </div>
              <p className="small">No portrait or biography is shown unless a licensed image is added to <code>public/img/drivers</code>. Nationality and car number are not in the collected data.</p>
            </div>
          </section>

          <div className="cols">
            <section className="section" aria-labelledby="res-h">
              <div className="section-head">
                <h2 id="res-h">{season} race by race</h2>
                <Field label="Season">{(id) => <select id={id} value={season} onChange={(e) => navigate(to(`/drivers/${code}`, { season: Number(e.target.value) }))}>{[...d.seasons_with_data].reverse().map((s) => <option key={s} value={s}>{s}</option>)}</select>}</Field>
              </div>
              <SortableTable caption={`${d.driver.name} ${season} results`} columns={cols} rows={d.results} rowKey={(r) => String(r.round)} defaultSort={{ key: 'round', dir: 'asc' }} />
              <p className="small">Points here are race points only. <Freshness iso={d.source_updated_at_utc} label="Data updated" /></p>
              {seasons.length > d.seasons_with_data.length && <p className="small">Earlier seasons appear in the season picker only when this driver raced in them.</p>}
            </section>
            <aside aria-label="Prediction">
              <section className="panel" aria-labelledby="dp-h">
                <h2 id="dp-h">Next prediction</h2>
                {event && <p className="muted">{event.race_name}</p>}
                {mine && snap.data ? (
                  <>
                    <p className="verdict"><span>{d.driver.name.split(' ').slice(-1)[0]} has a <strong>{formatPercent(mine.win_probability)}</strong> chance to win and <strong>{formatPercent(mine.podium_probability)}</strong> to finish on the podium.</span></p>
                    <p className="small">{snap.data.stage?.label}, made <Freshness iso={snap.data.created_at_utc} label="" />. An estimate, not a promise.</p>
                    <Link className="btn" to={`/history/${snap.data.snapshot_id}`}>Open the prediction</Link>
                  </>
                ) : <p>No race prediction is saved for the selected weekend yet, or this driver is not in it.</p>}
              </section>
            </aside>
          </div>
        </>
      )}
    </>
  )
}
