/** Team accents. Brand colours are public design data, used only as small accents. Unknown teams stay neutral. */
const COLOURS: Record<string, string> = {
  mercedes: '#27c4b0',
  ferrari: '#e8271f',
  'red-bull': '#3a5bd9',
  mclaren: '#ff8000',
  'aston-martin': '#2a9d7c',
  'alpine-f1-team': '#2f8fe8',
  williams: '#3d7bf0',
  'rb-f1-team': '#6692ff',
  audi: '#d63a2f',
  'haas-f1-team': '#9aa0a8',
  'cadillac-f1-team': '#b8a46a',
}

export function slugify(name: string | null | undefined): string {
  return (name ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

export function teamColour(name: string | null | undefined): string {
  return COLOURS[slugify(name)] ?? '#8a8f98'
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}
