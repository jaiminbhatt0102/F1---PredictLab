import { ArrowLeft } from 'lucide-react'
import { api } from '../api/client'
import type { TeamProfile } from '../api/types'
import { Portrait } from '../art/Photo'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { Link, to, useLocation } from '../router'
import { EmptyState, ErrorState, Freshness, Loading, PositionTile, SortableTable, type Column } from '../components/ui'
import { initials, teamColour } from '../team'

export default function TeamDetail({ slug }: { slug: string }) {
  const loc = useLocation()
  const { season: selSeason } = useSelection()
  const season = Number(loc.search.get('season')) || selSeason
  const data = useFetch(season ? (s) => api.team(season, slug, s) : null, [season, slug])
  const t = data.data
  const tint = teamColour(t?.team.name)
  const roundCols: Column<TeamProfile['rounds'][number]>[] = [
    { key: 'round', header: 'Round', render: (r) => <PositionTile value={r.round} />, sortValue: (r) => r.round },
    { key: 'race', header: 'Grand Prix', render: (r) => <Link to={`/races/${season}/${r.round}`}>{r.race_name}</Link>, sortValue: (r) => r.race_name },
    { key: 'drivers', header: 'Drivers (finish)', render: (r) => r.drivers.map((x, i) => <span key={`${x.driver_code}-${i}`}>{i > 0 && ' · '}{x.driver_code ? <Link to={`/drivers/${x.driver_code}?season=${season}`}>{x.driver_code}</Link> : '–'} {x.position ? `P${x.position}` : '–'}</span>) },
    { key: 'best', header: 'Best', align: 'right', priority: 'low', render: (r) => r.best_finish ?? '–', sortValue: (r) => r.best_finish },
    { key: 'pts', header: 'Pts', align: 'right', render: (r) => r.points, sortValue: (r) => r.points },
  ]
  return (
    <>
      <Link to={to('/teams', { season })} className="back"><ArrowLeft size={16} aria-hidden="true" />All teams</Link>
      {data.loading && <Loading label="Loading the team" />}
      {data.error && (data.error.status === 404
        ? <EmptyState title="This team has no races in this season" action={<Link className="btn" to={to('/teams', { season })}>Back to teams</Link>}>Try another season.</EmptyState>
        : <ErrorState error={data.error} onRetry={data.reload} />)}
      {t && season && (
        <>
          <section className="profile-head" aria-labelledby="team-h">
            <Portrait kind="teams" id={t.team.slug} alt={t.team.name} mono={initials(t.team.name)} tint={tint} />
            <div className="profile-copy">
              <div><h1 id="team-h">{t.team.name}</h1><p className="hero-where">{season} constructors’ championship</p></div>
              <div className="stats">
                <div className="stat"><strong>{t.standing.rank ? `P${t.standing.rank}` : '–'}</strong><span>Standing</span></div>
                <div className="stat"><strong>{t.standing.points ?? '–'}</strong><span>Points</span></div>
                <div className="stat"><strong>{t.standing.wins ?? '–'}</strong><span>Wins</span></div>
                <div className="stat"><strong>{t.standing.podiums ?? '–'}</strong><span>Podiums</span></div>
                <div className="stat"><strong>{t.standing.best_finish ?? '–'}</strong><span>Best finish</span></div>
              </div>
            </div>
          </section>
          <div className="cols">
            <section className="section" aria-labelledby="tr-h">
              <div className="section-head"><h2 id="tr-h">Race by race</h2></div>
              <SortableTable caption={`${t.team.name} ${season} results`} columns={roundCols} rows={t.rounds} rowKey={(r) => String(r.round)} defaultSort={{ key: 'round', dir: 'asc' }} />
              <p className="small">Points are race points only. <Freshness iso={t.source_updated_at_utc} label="Data updated" /></p>
            </section>
            <aside aria-label="Drivers">
              <section className="section" aria-labelledby="ln-h">
                <div className="section-head"><h2 id="ln-h">Drivers</h2></div>
                <ul className="rows">
                  {t.drivers.map((d) => (
                    <li key={d.driver_code}>
                      <Link className="row-link" to={`/drivers/${d.driver_code}?season=${season}`}>
                        <span className="pos">{d.races}</span>
                        <span className="name">{d.name}<span className="sub">{d.wins} wins · {d.podiums} podiums</span></span>
                        <span className="pts">{d.points}<span className="visually-hidden"> points</span></span>
                      </Link>
                    </li>
                  ))}
                </ul>
                <p className="small">The number on the left is races entered this season. A driver who changed teams may appear under both teams.</p>
              </section>
            </aside>
          </div>
        </>
      )}
    </>
  )
}
