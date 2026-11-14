import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { Portrait } from '../art/Photo'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { Link, navigate, to, useLocation } from '../router'
import { EmptyState, ErrorState, Field, Freshness, Loading, PageHeader } from '../components/ui'
import { initials, teamColour } from '../team'

export function useSeasonParam(): [number | null, (s: number) => void, number[]] {
  const { seasons } = useSelection()
  const loc = useLocation()
  const season = Number(loc.search.get('season')) || (seasons.length ? seasons[seasons.length - 1] : null)
  return [season, (s: number) => navigate(to(loc.path, { season: s })), seasons]
}

export default function Drivers() {
  const [season, setSeason, seasons] = useSeasonParam()
  const data = useFetch(season ? (s) => api.seasonSummary(season, s) : null, [season])
  const [team, setTeam] = useState('')
  const [query, setQuery] = useState('')
  const teams = useMemo(() => [...new Set((data.data?.drivers ?? []).map((d) => d.constructor_name).filter((t): t is string => !!t))].sort(), [data.data])
  const rank = useMemo(() => new Map((data.data?.drivers ?? []).map((d, i) => [d.driver_id, i + 1])), [data.data])
  const rows = useMemo(() => (data.data?.drivers ?? []).filter((d) => (!team || d.constructor_name === team) && (!query || d.driver_name.toLowerCase().includes(query.toLowerCase()) || (d.driver_code ?? '').toLowerCase() === query.toLowerCase())), [data.data, team, query])
  return (
    <>
      <PageHeader title="Drivers" lead="Everyone who raced this season, in championship order." actions={data.data && <Freshness iso={data.data.source_updated_at_utc} label="Data updated" />} />
      <section className="filters" aria-label="Filters">
        <Field label="Season">{(id) => <select id={id} value={season ?? ''} disabled={!seasons.length} onChange={(e) => setSeason(Number(e.target.value))}>{[...seasons].reverse().map((s) => <option key={s} value={s}>{s}</option>)}</select>}</Field>
        <Field label="Team">{(id) => <select id={id} value={team} onChange={(e) => setTeam(e.target.value)}><option value="">All teams</option>{teams.map((t) => <option key={t} value={t}>{t}</option>)}</select>}</Field>
        <Field label="Driver">{(id) => <input id={id} type="search" value={query} placeholder="Name or code" onChange={(e) => setQuery(e.target.value)} />}</Field>
      </section>
      {data.loading && <Loading label="Loading drivers" />}
      {data.error && <ErrorState error={data.error} onRetry={data.reload} />}
      {data.data && rows.length === 0 && <EmptyState title="No drivers match">Try clearing a filter.</EmptyState>}
      {data.data && rows.length > 0 && season && (
        <ul className="driver-grid" aria-label={`${season} drivers`}>
          {rows.map((d) => {
            const [first, ...rest] = d.driver_name.split(' ')
            return (
              <li key={d.driver_id}>
                <Link to={`/drivers/${d.driver_code}?season=${season}`} className="driver-card">
                  <Portrait kind="drivers" id={d.driver_code ?? ''} alt={`${d.driver_name}, ${d.constructor_name ?? ''}`} mono={initials(d.driver_name)} tint={teamColour(d.constructor_name)} />
                  <span className="dc-body">
                    <span className="first">{first}</span>
                    <strong>{rest.join(' ')}</strong>
                    <span className="team"><span className="team-bar" style={{ background: teamColour(d.constructor_name) }} aria-hidden="true" />{d.constructor_name ?? 'Team not recorded'}</span>
                    <span className="pts">P{rank.get(d.driver_id)} · {d.points} pts</span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
      <p className="small">Positions and points count race results only; sprint points are not included.</p>
    </>
  )
}
