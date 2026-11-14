import { useMemo, useState } from 'react'
import { CheckCircle2, MinusCircle } from 'lucide-react'
import type { OrderRow, PredictionResponse, RaceRow, SnapshotDetail } from '../api/types'
import { Link } from '../router'
import { slugify, teamColour } from '../team'
import { Banner, Disclosure, Field, Freshness, PositionTile, ProbBar, SortableTable, type Column } from './ui'
import { download, formatDateTime, formatPercent, toCsv } from '../lib/format'

type Shown = PredictionResponse | SnapshotDetail

function DriverLink({ code, name, season }: { code: string | null; name: string; season: number }) {
  return code ? <Link to={`/drivers/${code}?season=${season}`}>{name}</Link> : <>{name}</>
}

export function LeadPick({ row, season, label }: { row: RaceRow; season: number; label: string }) {
  return (
    <div className="lead-pick" aria-label={label}>
      <span className="rank" aria-hidden="true">1</span>
      <div>
        <h3><DriverLink code={row.driver_code} name={row.driver_name} season={season} /></h3>
        <span className="muted"><span className="team-bar" style={{ background: teamColour(row.constructor_name) }} aria-hidden="true" />{row.constructor_name}</span>
      </div>
      <div className="pct">{formatPercent(row.win_probability)}<small>chance to win</small></div>
    </div>
  )
}

export function LeadOrder({ row, season, label, what }: { row: OrderRow; season: number; label: string; what: string }) {
  return (
    <div className="lead-pick" aria-label={label}>
      <span className="rank" aria-hidden="true">1</span>
      <div>
        <h3><DriverLink code={row.driver_code} name={row.driver_name} season={season} /></h3>
        <span className="muted"><span className="team-bar" style={{ background: teamColour(row.constructor_name) }} aria-hidden="true" />{row.constructor_name}</span>
      </div>
      <div className="pct" style={{ fontSize: '1.15rem' }}>{what}<small>our best estimate</small></div>
    </div>
  )
}

export function PodiumStrip({ rows }: { rows: RaceRow[] }) {
  const top = [...rows].sort((a, b) => b.win_probability - a.win_probability).slice(0, 3)
  return (
    <ol className="podium" aria-label="Most likely winners">
      {top.map((r, i) => (
        <li key={r.driver_id} className={`podium-${i + 1}`}>
          <span className="podium-pos">{i + 1}</span>
          <strong>{r.driver_name}</strong>
          <span className="muted">{r.constructor_name}</span>
          <span className="podium-pct">{formatPercent(r.win_probability)} <small>to win</small></span>
        </li>
      ))}
    </ol>
  )
}

export function OrderTable({ rows, caption, season }: { rows: OrderRow[]; caption: string; season: number }) {
  const cols: Column<OrderRow>[] = [
    { key: 'pos', header: 'Position', render: (r) => <PositionTile value={r.predicted_order} />, sortValue: (r) => r.predicted_order },
    { key: 'driver', header: 'Driver', render: (r) => <><DriverLink code={r.driver_code} name={r.driver_name} season={season} /> <span className="code">{r.driver_code}</span></>, sortValue: (r) => r.driver_name },
    { key: 'team', header: 'Team', priority: 'low', render: (r) => <TeamLink name={r.constructor_name} season={season} />, sortValue: (r) => r.constructor_name },
  ]
  return <SortableTable caption={caption} columns={cols} rows={rows} rowKey={(r) => r.driver_id} defaultSort={{ key: 'pos', dir: 'asc' }} empty={<p className="muted">No drivers match those filters.</p>} />
}

export function RaceTable({ rows, caption, season }: { rows: RaceRow[]; caption: string; season: number }) {
  const cols: Column<RaceRow>[] = [
    { key: 'rank', header: 'Rank', render: (r) => <PositionTile value={r.win_rank} />, sortValue: (r) => r.win_rank },
    { key: 'driver', header: 'Driver', render: (r) => <><DriverLink code={r.driver_code} name={r.driver_name} season={season} /> <span className="code">{r.driver_code}</span></>, sortValue: (r) => r.driver_name },
    { key: 'team', header: 'Team', priority: 'low', render: (r) => <TeamLink name={r.constructor_name} season={season} />, sortValue: (r) => r.constructor_name },
    { key: 'grid', header: 'Starts', align: 'right', priority: 'low', render: (r) => r.grid ?? 'Not available', sortValue: (r) => r.grid },
    { key: 'win', header: 'Win chance', render: (r) => <ProbBar value={r.win_probability} label={`${r.driver_name} win chance`} />, sortValue: (r) => r.win_probability },
    { key: 'podium', header: 'Podium chance', render: (r) => <ProbBar value={r.podium_probability} label={`${r.driver_name} podium chance`} />, sortValue: (r) => r.podium_probability },
  ]
  const ranks = rows.map((r) => r.win_rank)
  return (
    <>
      <SortableTable caption={caption} columns={cols} rows={rows} rowKey={(r) => r.driver_id} defaultSort={{ key: 'win', dir: 'desc' }} empty={<p className="muted">No drivers match those filters.</p>} />
      {new Set(ranks).size < ranks.length && <p className="small">Drivers with the same chance share a rank.</p>}
    </>
  )
}

function TeamLink({ name, season }: { name: string | null; season: number }) {
  if (!name) return <>Not available</>
  return <Link to={`/teams/${slugify(name)}?season=${season}`}><span className="team-bar" style={{ background: teamColour(name) }} aria-hidden="true" />{name}</Link>
}

function Basis({ res }: { res: Shown }) {
  const req = res.requested
  const items: { ok: boolean; text: string }[] = [{ ok: true, text: 'Results of the earlier races this season and before' }]
  if (req.session === 'race') {
    items.push({ ok: true, text: 'This weekend’s qualifying result' })
    if (res.event?.is_sprint_weekend) items.push({ ok: true, text: 'This weekend’s sprint result' })
    const official = res.inputs?.grid_source === 'official_grid'
    items.push({ ok: true, text: official ? 'The official starting grid' : req.checkpoint === 'pre_race' ? 'Starting grid: the qualifying order (the official grid wasn’t available, so penalties are not included)' : 'Starting grid: the qualifying order' })
  } else {
    items.push({ ok: false, text: 'Nothing from this weekend yet. Qualifying, sprint and race results are not used.' })
  }
  const w = res.inputs?.weather
  items.push(req.use_weather
    ? { ok: true, text: `Weather forecast: used (beta). Air temperature ${w?.temperature_c ?? '–'} °C` }
    : { ok: false, text: 'Weather forecast: not used in this version' })
  return (
    <section aria-labelledby="basis-h" className="basis">
      <h3 id="basis-h">What this prediction is based on</h3>
      <ul>{items.map((i) => <li key={i.text}>{i.ok ? <CheckCircle2 size={16} aria-hidden="true" className="ok" /> : <MinusCircle size={16} aria-hidden="true" className="faint" />}<span>{i.text}</span><span className="visually-hidden">{i.ok ? ' (used)' : ' (not used)'}</span></li>)}</ul>
    </section>
  )
}

export function exportCsv(res: Shown) {
  const race = res.output_type === 'win_and_podium_probability'
  const cols = race
    ? ['driver_code', 'driver_name', 'constructor_name', 'grid', 'win_probability', 'win_rank', 'podium_probability', 'podium_rank']
    : ['predicted_order', 'driver_code', 'driver_name', 'constructor_name']
  const name = `f1-predictlab-${res.requested.season}-round-${res.requested.round}-${res.requested.checkpoint}${res.requested.use_weather ? '-weather-beta' : ''}.csv`
  download(name, toCsv(res.rows as unknown as Record<string, unknown>[], cols))
}

export function PredictionBody({ res, showTitle = true }: { res: Shown; showTitle?: boolean }) {
  const race = res.output_type === 'win_and_podium_probability'
  const sprint = res.output_type === 'predicted_sprint_position'
  const season = res.requested.season
  const [query, setQuery] = useState('')
  const [team, setTeam] = useState('')
  const teams = useMemo(() => [...new Set((res.rows as { constructor_name: string | null }[]).map((r) => r.constructor_name).filter((t): t is string => !!t))].sort(), [res.rows])
  const shown = useMemo(() => (res.rows as (OrderRow | RaceRow)[]).filter((r) => (!team || r.constructor_name === team) && (!query || r.driver_name.toLowerCase().includes(query.toLowerCase()) || (r.driver_code ?? '').toLowerCase() === query.toLowerCase())), [res.rows, team, query])
  const leader = race ? [...(res.rows as RaceRow[])].sort((a, b) => b.win_probability - a.win_probability)[0] : null
  return (
    <div className="result">
      {showTitle && (
        <div className="result-head">
          <div>
            <h2 id="res-h">{res.stage?.label}: {res.event_name ?? res.event?.race_name}</h2>
            <p className="muted">{res.output_label}{res.requested.use_weather ? ' · with the weather forecast (beta)' : ''}</p>
          </div>
          {res.kind === 'experimental' && <span className="model-label model-experimental">Beta</span>}
        </div>
      )}
      <p className="muted made">{res.stage?.uses}</p>
      {res.warnings.length > 0 && (
        <Banner tone="warn" title="Worth knowing"><span className="warn-list">{res.warnings.map((w) => <span key={w}>{w}</span>)}</span></Banner>
      )}
      {leader && <LeadPick row={leader} season={season} label="Most likely winner" />}
      {!race && res.rows.length > 0 && <LeadOrder row={[...(res.rows as OrderRow[])].sort((a, b) => a.predicted_order - b.predicted_order)[0]} season={season} label="Predicted fastest" what={sprint ? 'Predicted sprint winner' : 'Predicted pole'} />}
      <div className="filters" role="search" aria-label="Filter drivers">
        <Field label="Driver">{(id) => <input id={id} type="search" value={query} placeholder="Name or code" onChange={(e) => setQuery(e.target.value)} />}</Field>
        <Field label="Team">{(id) => <select id={id} value={team} onChange={(e) => setTeam(e.target.value)}><option value="">All teams</option>{teams.map((t) => <option key={t} value={t}>{t}</option>)}</select>}</Field>
      </div>
      {race ? (
        <RaceTable rows={shown as RaceRow[]} season={season} caption="Predicted win and podium chances for every driver" />
      ) : (
        <OrderTable rows={shown as OrderRow[]} season={season} caption={sprint ? 'Predicted sprint order' : 'Predicted qualifying order'} />
      )}
      <Basis res={res} />
      <div className="result-meta">
        <span className="muted">
          {res.created_at_utc && <Freshness iso={res.created_at_utc} label="Made" />}
          {res.trigger && <> · {res.trigger === 'automatic' ? 'made automatically' : 'made on request'}</>}
          {' · saved, so it can be checked against the result later'}
          {res.inputs?.data_version?.latest_completed_event && <><br />Data used: results up to {res.inputs.data_version.latest_completed_event.race_name}{res.inputs.data_version.dataset_updated_at_utc ? `, table built ${formatDateTime(res.inputs.data_version.dataset_updated_at_utc)}` : ''}.</>}
        </span>
        <button type="button" className="btn" onClick={() => exportCsv(res)}>Download as spreadsheet</button>
      </div>
      <Disclosure summary="How to read this">
        {race ? (
          <>
            <p>The percentages are chances, not promises. A driver on 10% would be expected to win about one race in ten from this position. Even the favourite loses most of the time.</p>
            <p>Rank 1 is the driver most likely to win. “Starts” is the grid position used.</p>
          </>
        ) : (
          <p>This is our best guess at the finishing order, built from recent form, team and circuit. Real sessions are full of surprises, so treat it as a starting point.</p>
        )}
      </Disclosure>
    </div>
  )
}
