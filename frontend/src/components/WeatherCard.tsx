import { CloudRain, Thermometer, Wind } from 'lucide-react'
import { api } from '../api/client'
import { useFetch } from '../hooks/useFetch'
import { ErrorState, Freshness, Loading } from './ui'
import { formatDateTime } from '../lib/format'

export function WeatherCard({ season, round }: { season: number | null; round: number | null }) {
  const weather = useFetch(season && round ? (s) => api.weather(season, round, s) : null, [season, round])
  const snap = weather.data?.forecast_snapshots[0]
  return (
    <section className="panel" aria-labelledby="wx-h">
      <h2 id="wx-h">Race-day weather</h2>
      {weather.loading && <Loading label="Loading the weather forecast" />}
      {weather.error && <ErrorState error={weather.error} onRetry={weather.reload} />}
      {weather.data && !snap && <p>No forecast has been saved for this Grand Prix yet. The app starts saving them about a week before the race.</p>}
      {snap && (
        <>
          <ul className="wx">
            <li><Thermometer size={18} aria-hidden="true" /><strong>{snap.temperature_c ?? '–'}{snap.temperature_c !== null && ' °C'}</strong><span>Air temperature</span></li>
            <li><CloudRain size={18} aria-hidden="true" /><strong>{snap.precipitation_mm ?? '–'}{snap.precipitation_mm !== null && ' mm'}</strong><span>Rain expected</span></li>
            <li><Wind size={18} aria-hidden="true" /><strong>{snap.wind_speed_kmh ?? '–'}{snap.wind_speed_kmh !== null && ' km/h'}</strong><span>Wind</span></li>
          </ul>
          <p className="small">Forecast for {formatDateTime(snap.weather_valid_time_utc)}. <Freshness iso={snap.fetched_at_utc} label="Saved" /></p>
          {snap.lead_time_check?.status === 'too_early' && <p className="small">This is an early forecast and can still change a lot. The app saves a new one every day, and again the day before the race.</p>}
          {snap.lead_time_check?.status === 'ok' && <p className="small">This forecast is close enough to race day to be used by the weather version of our prediction.</p>}
        </>
      )}
    </section>
  )
}
