import { useEffect, useState } from 'react'

/** Which licensed photos exist. Listed in public/img/manifest.json, so the app never requests a missing file. */
export type ImageKind = 'hero' | 'drivers' | 'teams'
type Manifest = Partial<Record<ImageKind, string[]>>

let cache: Promise<Manifest> | null = null
function load(): Promise<Manifest> {
  cache ??= fetch('/img/manifest.json').then((r) => (r.ok ? (r.json() as Promise<Manifest>) : {})).catch(() => ({}))
  return cache
}

export function useHasImage(kind: ImageKind, id: string | null | undefined): boolean {
  const [has, setHas] = useState(false)
  useEffect(() => {
    let live = true
    load().then((m) => { if (live) setHas(!!id && (m[kind] ?? []).includes(id)) })
    return () => { live = false }
  }, [kind, id])
  return has
}
