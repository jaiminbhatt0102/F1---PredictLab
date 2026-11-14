import type { ConstructorSummary, SeasonDriver } from '../api/types'
import { Link } from '../router'
import { slugify, teamColour } from '../team'

export function DriverStandings({ drivers, season, limit }: { drivers: SeasonDriver[]; season: number; limit?: number }) {
  return (
    <ol className="rows" aria-label={`${season} driver standings`}>
      {drivers.slice(0, limit).map((d, i) => (
        <li key={d.driver_id}>
          <Link to={`/drivers/${d.driver_code}?season=${season}`} className="row-link">
            <span className="pos">{i + 1}</span>
            <span className="name"><span className="team-bar" style={{ background: teamColour(d.constructor_name) }} aria-hidden="true" />{d.driver_name}<span className="sub">{d.constructor_name}</span></span>
            <span className="pts">{d.points}<span className="visually-hidden"> points</span></span>
          </Link>
        </li>
      ))}
    </ol>
  )
}

export function TeamStandings({ teams, season, limit }: { teams: ConstructorSummary['constructors']; season: number; limit?: number }) {
  return (
    <ol className="rows" aria-label={`${season} constructor standings`}>
      {teams.slice(0, limit).map((t, i) => (
        <li key={t.constructor_name}>
          <Link to={`/teams/${slugify(t.constructor_name)}?season=${season}`} className="row-link">
            <span className="pos">{i + 1}</span>
            <span className="name"><span className="team-bar" style={{ background: teamColour(t.constructor_name) }} aria-hidden="true" />{t.constructor_name}<span className="sub">{t.wins} {t.wins === 1 ? 'win' : 'wins'}</span></span>
            <span className="pts">{t.points}<span className="visually-hidden"> points</span></span>
          </Link>
        </li>
      ))}
    </ol>
  )
}
