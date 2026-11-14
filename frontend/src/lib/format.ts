const dateTime = new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return 'Not available'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'Not available' : dateTime.format(d)
}
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return 'Not available'
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
  return Number.isNaN(d.getTime()) ? 'Not available' : dateOnly.format(d)
}
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never'
  const diff = Math.max(0, now - new Date(iso).getTime())
  const m = Math.round(diff / 60000)
  if (m < 1) return 'less than a minute ago'
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'} ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} hour${h === 1 ? '' : 's'} ago`
  const d = Math.round(h / 24)
  return `${d} days ago`
}
export function formatPercent(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'Not available'
  const pct = v * 100
  if (pct > 0 && pct < 0.1) return '<0.1%'
  return `${pct.toFixed(pct < 10 ? 1 : 0)}%`
}
export function formatNumber(v: number | null | undefined, digits = 3): string {
  return v === null || v === undefined || Number.isNaN(v) ? 'Not available' : v.toFixed(digits)
}
export function words(value: string | null | undefined): string {
  if (!value) return 'Not available'
  const s = value.replaceAll('_', ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}
export function csvEscape(v: unknown): string {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}
export function toCsv(rows: Record<string, unknown>[], columns: string[]): string {
  return [columns.join(','), ...rows.map((r) => columns.map((c) => csvEscape(r[c])).join(','))].join('\n')
}
export function download(filename: string, text: string, mime = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function countdown(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null
  const diff = new Date(iso).getTime() - now
  if (Number.isNaN(diff) || diff <= 0) return null
  const mins = Math.floor(diff / 60000)
  const d = Math.floor(mins / 1440)
  const h = Math.floor((mins % 1440) / 60)
  const m = mins % 60
  if (d >= 1) return `${d} day${d === 1 ? '' : 's'}, ${h} hour${h === 1 ? '' : 's'}`
  if (h >= 1) return `${h} hour${h === 1 ? '' : 's'}, ${m} minute${m === 1 ? '' : 's'}`
  return `${m} minute${m === 1 ? '' : 's'}`
}
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return 'Not available'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'Not available' : new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(d)
}
