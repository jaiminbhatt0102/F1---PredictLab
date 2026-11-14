import { api } from '../api/client'
import { useSelection } from '../data'
import { useFetch } from '../hooks/useFetch'
import { ErrorState, Field, Freshness, Loading, PageHeader } from '../components/ui'
import { CalendarRows } from '../components/race'
import { useSeasonParam } from './Drivers'

export default function Calendar() {
  const [season, setSeason, seasons] = useSeasonParam()
  const { round } = useSelection()
  const events = useFetch(season ? (s) => api.events(season, s) : null, [season])
  const done = events.data?.events.filter((e) => e.weekend_stage === 'race_complete').length ?? 0
  return (
    <>
      <PageHeader title="Calendar" lead="Every Grand Prix of the season. Open a race for its sessions, predictions and results." actions={events.data && <Freshness iso={events.data.schedule_updated_at_utc} label="Schedule updated" />} />
      <section className="filters" aria-label="Season">
        <Field label="Season">{(id) => <select id={id} value={season ?? ''} disabled={!seasons.length} onChange={(e) => setSeason(Number(e.target.value))}>{[...seasons].reverse().map((s) => <option key={s} value={s}>{s}</option>)}</select>}</Field>
        {events.data && <p className="muted">{done} of {events.data.events.length} races finished</p>}
      </section>
      {events.loading && <Loading label="Loading the calendar" />}
      {events.error && <ErrorState error={events.error} onRetry={events.reload} />}
      {events.data && season && <CalendarRows events={events.data.events} season={season} currentRound={season === events.data.season ? (events.data.default_round ?? round) : null} />}
      <p className="small">Dates are the race day. Session times appear on each race page when the data source provides them.</p>
    </>
  )
}
