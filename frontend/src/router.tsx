import { useCallback, useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent, type ReactNode } from 'react'

/** A tiny History-API router. Real URLs (/drivers/VER), back/forward, no extra dependency. */
export type RouteName = 'home' | 'predictions' | 'results' | 'history' | 'historyDetail' | 'drivers' | 'driver' | 'teams' | 'team' | 'calendar' | 'race' | 'how' | 'updates' | 'notfound'

const ROUTES: { name: RouteName; pattern: string }[] = [
  { name: 'home', pattern: '/' },
  { name: 'predictions', pattern: '/predictions' },
  { name: 'results', pattern: '/results' },
  { name: 'history', pattern: '/history' },
  { name: 'historyDetail', pattern: '/history/:id' },
  { name: 'drivers', pattern: '/drivers' },
  { name: 'driver', pattern: '/drivers/:code' },
  { name: 'teams', pattern: '/teams' },
  { name: 'team', pattern: '/teams/:slug' },
  { name: 'calendar', pattern: '/calendar' },
  { name: 'race', pattern: '/races/:season/:round' },
  { name: 'how', pattern: '/how-it-works' },
  { name: 'updates', pattern: '/updates' },
]

export interface Match { name: RouteName; params: Record<string, string>; search: URLSearchParams; path: string }

export function match(path: string, search: string): Match {
  const clean = path.replace(/\/+$/, '') || '/'
  for (const r of ROUTES) {
    const a = r.pattern.split('/').filter(Boolean)
    const b = clean.split('/').filter(Boolean)
    if (a.length !== b.length) continue
    const params: Record<string, string> = {}
    const ok = a.every((seg, i) => (seg.startsWith(':') ? ((params[seg.slice(1)] = decodeURIComponent(b[i])), true) : seg === b[i]))
    if (ok) return { name: r.name, params, search: new URLSearchParams(search), path: clean }
  }
  return { name: 'notfound', params: {}, search: new URLSearchParams(search), path: clean }
}

// Old links used #/page?x=y. Turn them into real paths once, so bookmarks keep working.
const OLD: Record<string, string> = { home: '/', predictor: '/predictions', predictions: '/predictions', results: '/results', sessions: '/results', history: '/history', drivers: '/drivers', how: '/how-it-works', updates: '/updates' }
if (typeof window !== 'undefined' && window.location.hash.startsWith('#/')) {
  const [p, q = ''] = window.location.hash.slice(2).split('?')
  const target = p === '' ? '/' : OLD[p]
  if (target) window.history.replaceState(null, '', target + (q ? `?${q}` : ''))
}

const listeners = new Set<() => void>()
let snapshot = typeof window !== 'undefined' ? window.location.pathname + window.location.search : '/'
function emit() { snapshot = window.location.pathname + window.location.search; listeners.forEach((l) => l()) }
if (typeof window !== 'undefined') window.addEventListener('popstate', emit)

function subscribe(cb: () => void) { listeners.add(cb); return () => listeners.delete(cb) }

export function useLocation(): Match {
  const key = useSyncExternalStore(subscribe, () => snapshot, () => '/')
  const i = key.indexOf('?')
  return match(i < 0 ? key : key.slice(0, i), i < 0 ? '' : key.slice(i))
}

export function navigate(to: string, replace = false) {
  if (to === window.location.pathname + window.location.search) return
  if (replace) window.history.replaceState(null, '', to)
  else window.history.pushState(null, '', to)
  emit()
  window.scrollTo(0, 0)
}

export function useNavigate() { return useCallback((to: string, replace = false) => navigate(to, replace), []) }

export function to(path: string, query: Record<string, string | number | undefined | null> = {}): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  const s = q.toString()
  return s ? `${path}?${s}` : path
}

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> { to: string; children: ReactNode }
export function Link({ to: target, children, onClick, ...rest }: LinkProps) {
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e)
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || rest.target === '_blank') return
    e.preventDefault()
    navigate(target)
  }
  return <a href={target} onClick={click} {...rest}>{children}</a>
}
