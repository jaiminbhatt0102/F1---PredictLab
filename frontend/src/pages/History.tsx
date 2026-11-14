import { ArrowLeft, CheckCircle2, XCircle } from 'lucide-react'
import { api } from '../api/client'
import type { Comparison, SnapshotDetail } from '../api/types'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { Link, navigate, to, useLocation } from '../router'
import { EmptyState, ErrorState, Field, Freshness, Loading, PageHeader, PositionTile, SortableTable, Status, type Column } from '../components/ui'
import { PredictionBody } from '../components/PredictionView'
import { formatPercent } from '../lib/format'

const SESSION_WORD: Record<string, string> = { qualifying: 'Qualifying', sprint: 'Sprint', race: 'Race' }

export default function History() {
  const { search } = useLocation()
  const { seasons } = useSelection()
  const season = Number(search.get('season')) || undefined
  const round = Number(search.get('round')) || undefined
  const session = search.get('session') || undefined
  const kind = search.get('kind') || undefined
  const events = useFetch(season ? (s) => api.events(season, s) : null, [season])
  const list = useFetch((s) => api.history({ season, round, session, kind, limit: 60 }, s), [season, round, session, kind])
  const record = useFetch((s) => api.trackRecord(s), [])
  const set = (patch: Record<string, string | number | undefined>) => navigate(to('/history', { season, round, session, kind, ...patch }))
  const r = record.data

  return (
    <>
      <PageHeader title="Prediction history" lead="Every prediction we made, exactly as it was. After a race, each one is compared with what really happened." />
      <div className="cols">
        <div>
          <section className="filters" aria-label="Filters">
            <Field label="Season">{(id) => <select id={id} value={season ?? ''} onChange={(e) => set({ season: Number(e.target.value) || undefined, round: undefined })}><option value="">All seasons</option>{[...seasons].reverse().map((s) => <option key={s} value={s}>{s}</option>)}</select>}</Field>
            <Field label="Grand Prix">{(id) => <select id={id} value={round ?? ''} disabled={!season} onChange={(e) => set({ round: Number(e.target.value) || undefined })}><option value="">{season ? 'All Grands Prix' : 'Choose a season first'}</option>{events.data?.events.map((e) => <option key={e.round} value={e.round}>Round {e.round}: {e.race_name}</option>)}</select>}</Field>
            <Field label="Session">{(id) => <select id={id} value={session ?? ''} onChange={(e) => set({ session: e.target.value || undefined })}><option value="">All sessions</option><option value="qualifying">Qualifying</option><option value="sprint">Sprint</option><option value="race">Race</option></select>}</Field>
            <Field label="Type">{(id) => <select id={id} value={kind ?? ''} onChange={(e) => set({ kind: e.target.value || undefined })}><option value="">All</option><option value="production">Main predictions</option><option value="experimental">With weather (beta)</option></select>}</Field>
          </section>
          {list.loading && <Loading label="Loading saved predictions" />}
          {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
          {list.data && list.data.total === 0 && <EmptyState title="No saved predictions match">{season || session || kind ? 'Try clearing a filter.' : 'The app saves a prediction automatically in race week. You can also make one on the Predictions page.'}</EmptyState>}
          {list.data && list.data.items.length > 0 && (
            <ul className="cards" aria-label="Saved predictions">
              {list.data.items.map((i) => (
                <li key={i.snapshot_id}>
                  <Link className="card" to={`/history/${i.snapshot_id}`}>
                    <span className="card-top"><strong>{i.event_name}</strong> <span className="muted">{i.requested.season}</span></span>
                    <span>{i.stage?.label} · {SESSION_WORD[i.requested.session]}{i.kind === 'experimental' ? ' · with weather (beta)' : ''}</span>
                    <span className="muted">{i.headline?.driver_name ? `Leading pick: ${i.headline.driver_name}${i.headline.win_probability ? ` (${formatPercent(i.headline.win_probability)})` : ''}` : ''}</span>
                    <span className="muted"><Freshness iso={i.created_at_utc} label="Made" /> · {i.trigger === 'automatic' ? 'automatically' : 'on request'}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <aside aria-label="Our record">
          <section className="panel" aria-labelledby="rec-h">
            <h2 id="rec-h">Our record so far</h2>
            {record.loading && <Loading />}
            {record.error && <ErrorState error={record.error} onRetry={record.reload} />}
            {r && r.race.compared + r.qualifying.compared + r.sprint.compared === 0 && <p>Nothing to compare yet. After each race weekend the app checks its predictions against the real results and the score appears here.</p>}
            {r && r.race.compared > 0 && <p><strong>Races:</strong> we picked the winner in {r.race.winner_correct} of {r.race.compared}, and {r.race.podium_hits} of our {r.race.podium_picks} podium picks finished on the podium.</p>}
            {r && r.qualifying.compared > 0 && <p><strong>Qualifying:</strong> on average {r.qualifying.average_places_off} places off per driver across {r.qualifying.compared} sessions.</p>}
            {r && r.sprint.compared > 0 && <p><strong>Sprints:</strong> on average {r.sprint.average_places_off} places off per driver across {r.sprint.compared} sprints.</p>}
            <p className="small">Only predictions made before a session count. Each stage of each race is counted once.</p>
          </section>
        </aside>
      </div>
    </>
  )
}

function Compare({ c, snap }: { c: Comparison; snap: SnapshotDetail }) {
  const h = c.headline
  const cols: Column<Comparison['rows'][number]>[] = [
    { key: 'pred', header: 'Our rank', render: (r) => <PositionTile value={r.predicted_rank} />, sortValue: (r) => r.predicted_rank },
    { key: 'driver', header: 'Driver', render: (r) => r.driver_code ? <><Link to={`/drivers/${r.driver_code}?season=${snap.requested.season}`}>{r.driver_name}</Link> <span className="code">{r.driver_code}</span></> : r.driver_name, sortValue: (r) => r.driver_name },
    { key: 'actual', header: 'Finished', render: (r) => <PositionTile value={r.actual_position} />, sortValue: (r) => r.actual_position },
    ...(c.kind === 'race' ? [] : [{ key: 'off', header: 'Places off', align: 'right' as const, render: (r: Comparison['rows'][number]) => (r.places_off === null || r.places_off === undefined ? '–' : r.places_off === 0 ? 'Exact' : r.places_off), sortValue: (r: Comparison['rows'][number]) => r.places_off ?? null }]),
  ]
  return (
    <section className="panel" aria-labelledby="how-h">
      <h2 id="how-h">How it turned out</h2>
      {c.kind === 'race' ? (
        <>
          <p className="verdict">
            {h.winner_correct ? <CheckCircle2 size={20} className="ok" aria-hidden="true" /> : <XCircle size={20} className="bad" aria-hidden="true" />}
            <span>We picked <strong>{h.predicted_winner}</strong> to win. <strong>{h.actual_winner}</strong> won. <span className="visually-hidden">{h.winner_correct ? 'Correct.' : 'Not correct.'}</span></span>
          </p>
          <p>{h.podium_hits} of our {h.podium_picks} podium picks finished on the podium.</p>
        </>
      ) : (
        <p className="verdict"><span>On average we were <strong>{h.average_places_off} places</strong> off per driver. {h.exact_matches} of {h.drivers_compared} drivers were in exactly the right place, and {h.top3_hits} of our top 3 were in the real top 3.</span></p>
      )}
      <SortableTable caption={`${snap.stage?.label}: our prediction against the real result`} columns={cols} rows={c.rows} rowKey={(r) => `${r.driver_code}-${r.predicted_rank}`} defaultSort={{ key: 'pred', dir: 'asc' }} />
    </section>
  )
}

export function HistoryDetail({ id }: { id: string }) {
  const snap = useFetch((s) => api.snapshot(id, s), [id])
  const s = snap.data
  return (
    <>
      <Link to="/history" className="back"><ArrowLeft size={16} aria-hidden="true" />All predictions</Link>
      {snap.loading && <Loading label="Loading the prediction" />}
      {snap.error && <ErrorState error={snap.error} onRetry={snap.reload} />}
      {s && (
        <>
          <PageHeader title={s.event_name ?? 'Prediction'} lead={<>{s.stage?.label} · {SESSION_WORD[s.requested.session]} · <Freshness iso={s.created_at_utc} label="made" /> · <Status tone="neutral">Saved and unchanged</Status></>} />
          {s.comparison ? <Compare c={s.comparison} snap={s} /> : <p className="panel muted">The real result isn’t in yet, so there is nothing to compare. It will be compared automatically after the session.</p>}
          <section className="panel" aria-labelledby="orig-h">
            <h2 id="orig-h">The prediction as it was made</h2>
            <PredictionBody res={s} showTitle={false} />
          </section>
        </>
      )}
    </>
  )
}
