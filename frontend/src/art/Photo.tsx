import { useState, type CSSProperties, type ReactNode } from 'react'
import { useHasImage, type ImageKind } from './manifest'

/** A stored photo when one is listed in the manifest, and a designed fallback otherwise. No broken images, no empty boxes. */
export function Photo({ kind, id, alt, fallback }: { kind: ImageKind; id: string | null | undefined; alt: string; fallback: ReactNode }) {
  const has = useHasImage(kind, id)
  const [failed, setFailed] = useState(false)
  if (!has || failed) return <>{fallback}</>
  return <img src={`/img/${kind}/${id}.jpg`} alt={alt} loading="lazy" decoding="async" onError={() => setFailed(true)} />
}

export function Portrait({ kind, id, alt, mono, tint, className }: { kind: 'drivers' | 'teams'; id: string; alt: string; mono: string; tint: string; className?: string }) {
  const has = useHasImage(kind, id)
  const [failed, setFailed] = useState(false)
  const show = has && !failed
  return (
    <div className={`portrait ${show ? 'photo' : ''} ${className ?? ''}`} style={{ '--tint': tint } as CSSProperties}>
      <span className="mono" aria-hidden="true">{mono}</span>
      {show ? <img src={`/img/${kind}/${id}.jpg`} alt={alt} loading="lazy" decoding="async" onError={() => setFailed(true)} /> : <span className="visually-hidden">{alt}</span>}
    </div>
  )
}
