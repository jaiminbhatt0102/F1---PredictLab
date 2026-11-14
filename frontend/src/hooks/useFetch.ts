import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface FetchState<T> { data: T | null; error: ApiError | null; loading: boolean; reload: () => void }

/** Runs `load` whenever `deps` change; cancels the previous request so stale responses are ignored. */
export function useFetch<T>(load: ((signal: AbortSignal) => Promise<T>) | null, deps: unknown[]): FetchState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(load !== null)
  const [tick, setTick] = useState(0)
  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => {
    const fn = loadRef.current
    if (!fn) { setLoading(false); setData(null); setError(null); return }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    fn(controller.signal)
      .then((value) => { if (!controller.signal.aborted) { setData(value); setLoading(false) } })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setData(null)
        setError(err instanceof ApiError ? err : new ApiError('offline', 'unknown', 'Something went wrong.'))
        setLoading(false)
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload }
}
