import { Field, Status } from '../components/ui'
import { useSelection } from '../data'
import { stageLabel } from '../lib/stage'

/** Season and Grand Prix choice, with where the weekend stands. */
export function ContextBar() {
  const { season, round, event, seasons, events, select } = useSelection()
  return (
    <section className="context-bar" aria-label="Choose a Grand Prix">
      <Field label="Season">
        {(id) => (
          <select id={id} value={season ?? ''} disabled={!seasons.length} onChange={(e) => select({ season: Number(e.target.value) })}>
            {seasons.length === 0 && <option value="">Unavailable</option>}
            {[...seasons].reverse().map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </Field>
      <div className="field grow">
        <label htmlFor="gp-select">Grand Prix</label>
        <select id="gp-select" value={round ?? ''} disabled={!events.data} onChange={(e) => select({ round: Number(e.target.value) })}>
          {!events.data && <option value="">{events.loading ? 'Loading schedule' : 'Schedule unavailable'}</option>}
          {events.data?.events.map((e) => <option key={e.round} value={e.round}>Round {e.round}: {e.race_name}</option>)}
        </select>
      </div>
      {event && (
        <div className="context-note">
          <span className="muted">Where we are</span>
          <Status tone={event.weekend_stage === 'race_complete' ? 'ok' : event.weekend_stage === 'upcoming' ? 'neutral' : 'warn'}>{stageLabel(event.weekend_stage)}</Status>
        </div>
      )}
    </section>
  )
}
