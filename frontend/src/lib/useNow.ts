import { useEffect, useState } from 'react'

export function useNow(everyMs = 30000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), everyMs); return () => window.clearInterval(t) }, [everyMs])
  return now
}
