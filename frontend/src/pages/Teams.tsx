import { api } from '../api/client'
import { Portrait } from '../art/Photo'
import { useFetch } from '../hooks/useFetch'
import { Link } from '../router'
import { ErrorState, Field, Loading, PageHeader } from '../components/ui'
import { initials, slugify, teamColour } from '../team'
import { useSeasonParam } from './Drivers'

export default function Teams() {
  const [season, setSeason, seasons] = useSeasonParam()
  const data = useFetch(season ? (s) => api.constructors(season, s) : null, [season])
  return (
    <>
      <PageHeader title="Teams" lead="The constructors' championship, with each team's drivers and results." />
      <section className="filters" aria-label="Season">
        <Field label="Season">{(id) => <select id={id} value={season ?? ''} disabled={!seasons.length} onChange={(e) => setSeason(Number(e.target.value))}>{[...seasons].reverse().map((s) => <option key={s} value={s}>{s}</option>)}</select>}</Field>
      </section>
      {data.loading && <Loading label="Loading teams" />}
      {data.error && <ErrorState error={data.error} onRetry={data.reload} />}
      {data.data && season && (
        <ul className="team-grid" aria-label={`${season} teams`}>
          {data.data.constructors.map((t, i) => (
            <li key={t.constructor_name}>
              <Link to={`/teams/${slugify(t.constructor_name)}?season=${season}`} className="team-card">
                <Portrait kind="teams" id={slugify(t.constructor_name)} alt={t.constructor_name} mono={initials(t.constructor_name)} tint={teamColour(t.constructor_name)} />
                <span className="dc-body">
                  <strong>{t.constructor_name}</strong>
                  <span className="team">P{i + 1} · {t.wins} {t.wins === 1 ? 'win' : 'wins'} · {t.podiums} podiums</span>
                  <span className="pts">{t.points} pts</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="small">Points count race results only; sprint points are not included.</p>
    </>
  )
}
