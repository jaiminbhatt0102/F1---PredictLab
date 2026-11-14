import { useEffect, useRef, useState } from 'react'
import { Menu, Moon, Sun, X } from 'lucide-react'
import { Link, to, useLocation } from '../router'
import { useSelection } from '../data'
import { useTheme } from '../theme'

const NAV = [
  { label: 'This weekend', path: '/', match: ['home', 'race'] },
  { label: 'Predictions', path: '/predictions', match: ['predictions'] },
  { label: 'Results', path: '/results', match: ['results'] },
  { label: 'Calendar', path: '/calendar', match: ['calendar'] },
  { label: 'Drivers', path: '/drivers', match: ['drivers', 'driver'] },
  { label: 'Teams', path: '/teams', match: ['teams', 'team'] },
  { label: 'History', path: '/history', match: ['history', 'historyDetail'] },
  { label: 'How it works', path: '/how-it-works', match: ['how'] },
  { label: 'Updates', path: '/updates', match: ['updates'] },
]
const KEEP_EVENT = new Set(['/', '/predictions', '/results'])

export function SiteHeader() {
  const loc = useLocation()
  const { season, round, status } = useSelection()
  const [theme, toggle] = useTheme()
  const [open, setOpen] = useState(false)
  const btn = useRef<HTMLButtonElement>(null)

  useEffect(() => { setOpen(false) }, [loc.path])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); btn.current?.focus() } }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = '' }
  }, [open])

  const href = (path: string) => (KEEP_EVENT.has(path) ? to(path, { season, round }) : path)
  const links = NAV.map((n) => {
    const current = n.match.includes(loc.name)
    return <Link key={n.path} to={href(n.path)} aria-current={current ? 'page' : undefined}>{n.label}</Link>
  })
  const engine = status.error ? 'bad' : status.data?.status === 'ready' ? 'ok' : status.data ? 'warn' : ''
  const engineText = status.error ? 'Engine offline' : status.data ? (status.data.status === 'ready' ? 'Ready' : 'Needs attention') : 'Checking'

  return (
    <header className="site-header">
      <div className="header-inner">
        <Link to={href('/')} className="brand"><span className="brand-mark" aria-hidden="true" />F1 PredictLab</Link>
        <nav className="main-nav" aria-label="Main">{links}</nav>
        <div className="header-actions">
          <Link to="/updates" className={`engine-dot ${engine}`} title="Open Updates"><i aria-hidden="true" />{engineText}</Link>
          <button type="button" className="icon-btn" onClick={toggle} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            {theme === 'dark' ? <Sun size={19} aria-hidden="true" /> : <Moon size={19} aria-hidden="true" />}
          </button>
          <button ref={btn} type="button" className="icon-btn menu-btn" aria-expanded={open} aria-controls="mobile-nav" onClick={() => setOpen((v) => !v)}>
            {open ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
            <span className="visually-hidden">{open ? 'Close menu' : 'Open menu'}</span>
          </button>
        </div>
      </div>
      <nav id="mobile-nav" className={`mobile-nav ${open ? 'open' : ''}`} aria-label="Main (mobile)" hidden={false}>{links}</nav>
    </header>
  )
}
