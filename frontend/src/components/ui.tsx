import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, CheckCircle2, CircleDashed, Clock, Info, RefreshCw, WifiOff, XCircle } from 'lucide-react'
import type { ApiError } from '../api/client'
import { formatDateTime, formatPercent, timeAgo, words } from '../lib/format'

export function PageHeader({ title, lead, actions }: { title: string; lead?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {lead && <p className="lead">{lead}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

export type Tone = 'ok' | 'warn' | 'bad' | 'neutral'
const toneIcon = { ok: CheckCircle2, warn: AlertTriangle, bad: XCircle, neutral: CircleDashed }

/** Status always carries an icon and a word, never colour alone. */
export function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  const Icon = toneIcon[tone]
  return <span className={`status status-${tone}`}><Icon size={14} aria-hidden="true" />{children}</span>
}

export function statusTone(status: string | null | undefined): Tone {
  if (status === 'ready' || status === 'complete' || status === 'available' || status === 'ok') return 'ok'
  if (status === 'partial' || status === 'stale' || status === 'pending' || status === 'too_early' || status === 'too_late') return 'warn'
  if (status === 'not_ready' || status === 'failed' || status === 'missing') return 'bad'
  return 'neutral'
}

export function ModelLabel({ status }: { status: 'production' | 'candidate' | 'experimental' | 'baseline' }) {
  const text = { production: 'Production', candidate: 'Candidate', experimental: 'Experimental, weather-assisted', baseline: 'Baseline' }[status]
  return <span className={`model-label model-${status}`}>{text}</span>
}

export function Freshness({ iso, label = 'Last updated' }: { iso: string | null | undefined; label?: string }) {
  if (!iso) return <span className="freshness muted"><Clock size={13} aria-hidden="true" />{label}: not recorded</span>
  return (
    <span className="freshness">
      <Clock size={13} aria-hidden="true" />
      {label} <time dateTime={iso} title={formatDateTime(iso)}>{timeAgo(iso)}</time>
      <span className="visually-hidden"> ({formatDateTime(iso)})</span>
    </span>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="skeleton" aria-hidden="true" />
      <div className="skeleton short" aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const offline = error.kind === 'offline' || error.kind === 'timeout'
  return (
    <div className="state error" role="alert">
      {offline ? <WifiOff size={20} aria-hidden="true" /> : <AlertTriangle size={20} aria-hidden="true" />}
      <div>
        <h3>{offline ? 'Can’t reach the backend' : 'The server couldn’t do that'}</h3>
        <p>{offline ? 'The app’s engine isn’t running, or it was closed. Start it again and refresh this page. No sample data is shown while it is offline.' : error.message}</p>
        {offline && <code className="cmd">python run_app.py</code>}
        {onRetry && <button type="button" className="btn" onClick={onRetry}><RefreshCw size={15} aria-hidden="true" />Try again</button>}
      </div>
    </div>
  )
}

export function Banner({ tone, title, children }: { tone: Tone; title: string; children?: ReactNode }) {
  const Icon = tone === 'neutral' ? Info : toneIcon[tone]
  return (
    <div className={`banner banner-${tone}`} role={tone === 'bad' ? 'alert' : 'note'}>
      <Icon size={18} aria-hidden="true" />
      <div><strong>{title}</strong>{children && <p>{children}</p>}</div>
    </div>
  )
}

export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="disclosure">
      <summary>{summary}</summary>
      <div className="disclosure-body">{children}</div>
    </details>
  )
}

export function ProbBar({ value, label }: { value: number | null; label: string }) {
  if (value === null) return <span className="muted">Not available</span>
  const width = Math.min(100, Math.max(0, value * 100))
  return (
    <div className="prob" role="img" aria-label={`${label}: ${formatPercent(value)}`}>
      <div className="prob-track" aria-hidden="true"><div className="prob-fill" style={{ width: `${width}%` }} /></div>
      <span className="prob-num" aria-hidden="true">{formatPercent(value)}</span>
    </div>
  )
}

export function PositionTile({ value }: { value: number | string | null }) {
  return <span className="pos">{value ?? '–'}</span>
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string, describedBy: string | undefined) => ReactNode }) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id, hintId)}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  )
}

export interface Column<T> {
  key: string
  header: string
  render?: (row: T) => ReactNode
  sortValue?: (row: T) => number | string | null
  align?: 'right' | 'left'
  sortable?: boolean
  priority?: 'low'
}

export function SortableTable<T>({ caption, columns, rows, rowKey, defaultSort, empty }: {
  caption: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  defaultSort?: { key: string; dir: 'asc' | 'desc' }
  empty?: ReactNode
}) {
  const [sort, setSort] = useState(defaultSort ?? null)
  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    const get = col?.sortValue
    if (!get) return rows
    return [...rows].sort((a, b) => {
      const x = get(a); const y = get(b)
      if (x === null && y === null) return 0
      if (x === null) return 1
      if (y === null) return -1
      const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
      return sort.dir === 'asc' ? r : -r
    })
  }, [rows, sort, columns])
  const sortedBy = sort ? columns.find((c) => c.key === sort.key) : null
  if (rows.length === 0) return <>{empty ?? <EmptyState title="No rows to show" />}</>
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={`${caption} (scrollable)`}>
      <table className="data">
        <caption>
          <span className="visually-hidden">{caption}. </span>
          <span className="sort-note" aria-live="polite">{sortedBy ? `Sorted by ${sortedBy.header.toLowerCase()}, ${sort?.dir === 'asc' ? 'lowest first' : 'highest first'}` : 'Original order'}</span>
        </caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key
              const can = c.sortable !== false && !!c.sortValue
              return (
                <th key={c.key} scope="col" className={`${c.align === 'right' ? 'num' : ''} ${c.priority === 'low' ? 'low' : ''}`} aria-sort={active ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  {can ? (
                    <button type="button" className="th-btn" onClick={() => setSort(active ? { key: c.key, dir: sort?.dir === 'asc' ? 'desc' : 'asc' } : { key: c.key, dir: 'asc' })}>
                      {c.header}
                      {active ? (sort?.dir === 'asc' ? <ArrowUp size={13} aria-hidden="true" /> : <ArrowDown size={13} aria-hidden="true" />) : <ArrowUpDown size={13} aria-hidden="true" className="faint" />}
                    </button>
                  ) : c.header}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => (
                <td key={c.key} className={`${c.align === 'right' ? 'num' : ''} ${c.priority === 'low' ? 'low' : ''}`}>
                  {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? 'Not available')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function KeyValues({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="kv">
      {items.map((i) => (<div key={i.label}><dt>{i.label}</dt><dd>{i.value}</dd></div>))}
    </dl>
  )
}

export { words }

/** Native <dialog> gives focus trapping and Escape handling. Used only for actions with consequences. */
export function ConfirmDialog({ open, title, children, confirmLabel, onConfirm, onCancel }: {
  open: boolean; title: string; children: ReactNode; confirmLabel: string; onConfirm: () => void; onCancel: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog ref={ref} className="dialog" aria-labelledby="dlg-title" onCancel={(e) => { e.preventDefault(); onCancel() }}>
      <h2 id="dlg-title">{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn primary" onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </dialog>
  )
}
