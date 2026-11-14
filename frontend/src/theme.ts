import { useCallback, useEffect, useState } from 'react'

export type Theme = 'dark' | 'light'
const KEY = 'f1-theme'

function initial(): Theme {
  try {
    if (localStorage.getItem(KEY) === 'light') return 'light'
  } catch { /* storage can be blocked; stay dark */ }
  return 'dark'
}

/** Dark is the default for everyone. A visitor's choice of light is remembered on this device only. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(initial)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0e0f11' : '#f5f2ea')
    try { localStorage.setItem(KEY, theme) } catch { /* ignore */ }
  }, [theme])
  const toggle = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), [])
  return [theme, toggle]
}
