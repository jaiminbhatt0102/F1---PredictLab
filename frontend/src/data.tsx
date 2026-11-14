import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'
import { api } from './api/client'
import type { EventInfo, EventsResponse, StatusResponse } from './api/types'
import { useFetch, type FetchState } from './hooks/useFetch'
import { navigate, to, useLocation } from './router'

interface Selection {
  season: number | null
  round: number | null
  event: EventInfo | null
  seasons: number[]
  events: FetchState<EventsResponse>
  status: FetchState<StatusResponse>
  select: (next: { season?: number; round?: number }) => void
}
const Ctx = createContext<Selection | null>(null)

/** Season, Grand Prix and backend status, shared by every page. The choice lives in the address (?season=2026&round=18). */
export function SelectionProvider({ children }: { children: ReactNode }) {
  const loc = useLocation()
  const status = useFetch((s) => api.status(s), [])
  const seasons = status.data?.data.seasons ?? []
  const season = Number(loc.search.get('season')) || (seasons.length ? seasons[seasons.length - 1] : null)
  const events = useFetch(season ? (s) => api.events(season, s) : null, [season])
  const round = Number(loc.search.get('round')) || events.data?.default_round || null
  const event = events.data?.events.find((e) => e.round === round) ?? null
  const select = useCallback((next: { season?: number; round?: number }) => {
    const q = Object.fromEntries(loc.search.entries())
    const seasonChanged = next.season !== undefined && next.season !== season
    navigate(to(loc.path, { ...q, season: next.season ?? season, round: seasonChanged ? undefined : next.round ?? round }))
  }, [loc.path, loc.search, season, round])
  const value = useMemo(() => ({ season, round, event, seasons, events, status, select }), [season, round, event, seasons, events, status, select])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSelection(): Selection {
  const v = useContext(Ctx)
  if (!v) throw new Error('useSelection needs SelectionProvider')
  return v
}
