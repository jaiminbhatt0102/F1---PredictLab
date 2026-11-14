import { api } from '../api/client'
import type { SessionName, SessionRow } from '../api/types'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { Link, navigate, to, useLocation } from '../router'
import { ContextBar } from '../layout/ContextBar'
import { Disclosure, EmptyState, ErrorState, Freshness, Loading, PageHeader, PositionTile, SortableTable, Status, type Column } from '../components/ui'
import { slugify, teamColour } from '../team'

const TABS: { id: SessionName; label: string }[] = [{ id: 'qualifying', label: 'Qualifying' }, { id: 'sprint', label: 'Sprint' }, { id: 'race', label: 'Race' }]
const name = (r: SessionRow) => `${r.driver_given_name ?? ''} ${r.driver_family_name ?? ''}`.trim() || 'Not available'

export function resultColumns(tab: SessionName, season: number): Column<SessionRow>[] {
  return [
    { key: 'position', header: 'Pos', render: (r) => <PositionTile value={r.position} />, sortValue: (r) => r.position },
    { key: 'driver', header: 'Driver', render: (r) => r.driver_code ? <><Link to={`/drivers/${r.driver_code}?season=${season}`}>{name(r)}</Link> <span className="code">{r.driver_code}</span></> : name(r), sortValue: (r) => name(r) },
    { key: 'team', header: 'Team', priority: 'low', render: (r) => r.constructor_name ? <Link to={`/teams/${slugify(r.constructor_name)}?season=${season}`}><span className="team-bar" style={{ background: teamColour(r.constructor_name) }} aria-hidden="true" />{r.constructor_name}</Link> : 'Not available', sortValue: (r) => r.constructor_name },
    ...(tab === 'qualifying'
      ? [
          { key: 'q1', header: 'Q1', priority: 'low' as const, render: (r: SessionRow) => r.q1 || '–' },
          { key: 'q2', header: 'Q2', priority: 'low' as const, render: (r: SessionRow) => r.q2 || '–' },
          { key: 'q3', header: 'Q3', priority: 'low' as const, render: (r: SessionRow) => r.q3 || '–' },
        ]
      : [
          { key: 'grid', header: 'Grid', align: 'right' as const, priority: 'low' as const, render: (r: SessionRow) => r.grid ?? '–', sortValue: (r: SessionRow) => r.grid ?? null },
          { key: 'time', header: 'Time / gap', priority: 'low' as const, render: (r: SessionRow) => r.time || '–' },
          { key: 'status', header: 'Status', priority: 'low' as const, render: (r: SessionRow) => r.status || '–' },
          { key: 'points', header: 'Pts', align: 'right' as const, render: (r: SessionRow) => r.points ?? '–', sortValue: (r: SessionRow) => r.points ?? null },
        ]),
  ]
}

export default function Results() {
  const { season, round, event } = useSelection()
  const search = useLocation().search
  const tab = (TABS.find((t) => t.id === search.get('tab'))?.id ?? 'race') as SessionName
  const sessions = useFetch(season && round ? (s) => api.sessions(season, round, s) : null, [season, round])
  const predicted = useFetch(season && round ? (s) => api.history({ season, round, session: tab, kind: 'production', limit: 10 }, s) : null, [season, round, tab])
  const block = sessions.data?.sessions[tab]

  return (
    <>
      <ContextBar />
      <PageHeader title="Results" lead="What actually happened. These are real results from the collected data, never predictions." />
      <div className="segmented" role="group" aria-label="Session">
        {TABS.map((t) => (
          <button key={t.id} type="button" aria-pressed={tab === t.id} onClick={() => navigate(to('/results', { season, round, tab: t.id }))}>{t.label}</button>
        ))}
      </div>
      {sessions.loading && <Loading label="Loading results" />}
      {sessions.error && <ErrorState error={sessions.error} onRetry={sessions.reload} />}
      {!sessions.loading && !sessions.error && !event && <EmptyState title="Choose a Grand Prix">Pick a season and Grand Prix above.</EmptyState>}
      {block && season && (
        <section className="panel" aria-labelledby="actual-h">
          <div className="result-head">
            <h2 id="actual-h">{event?.race_name}: {TABS.find((t) => t.id === tab)?.label.toLowerCase()} result</h2>
            <span className="status-row">
              <Status tone={block.status === 'complete' ? 'ok' : 'neutral'}>{block.status === 'complete' ? 'Finished' : block.status === 'pending' ? 'Still to come' : 'No sprint'}</Status>
              {block.status === 'complete' && <Freshness iso={block.source_updated_at_utc} label="Data updated" />}
            </span>
          </div>
          {block.status === 'not_applicable' && <EmptyState title="No sprint at this Grand Prix">{event?.race_name} uses the standard weekend format.</EmptyState>}
          {block.status === 'pending' && <EmptyState title="Not finished yet">The result appears here automatically once the session is over and the data has updated.</EmptyState>}
          {block.status === 'complete' && <SortableTable caption={`${tab} classification`} columns={resultColumns(tab, season)} rows={block.rows} rowKey={(r) => `${r.driver_code}-${r.position}`} defaultSort={{ key: 'position', dir: 'asc' }} />}
          {tab === 'qualifying' && (
            <Disclosure summary="Why the starting grid can differ from qualifying">
              <p>Penalties and other official changes can move drivers on the grid. The Race tab shows where each driver actually started.</p>
            </Disclosure>
          )}
        </section>
      )}
      <section className="panel" aria-labelledby="pred-h">
        <h2 id="pred-h">What we predicted</h2>
        {predicted.loading && <Loading />}
        {predicted.error && <ErrorState error={predicted.error} onRetry={predicted.reload} />}
        {predicted.data && predicted.data.items.length === 0 && <p>No prediction was saved for this session.</p>}
        {predicted.data && predicted.data.items.length > 0 && (
          <ul className="plain">
            {predicted.data.items.map((i) => (
              <li key={i.snapshot_id}>
                <Link to={`/history/${i.snapshot_id}`}>{i.stage?.label}</Link>
                <span className="muted">{i.headline?.driver_name ? `Leading pick: ${i.headline.driver_name}` : ''}</span>
                <span className="muted">{block?.status === 'complete' ? 'Open to compare with the result' : 'Waiting for the result'}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
