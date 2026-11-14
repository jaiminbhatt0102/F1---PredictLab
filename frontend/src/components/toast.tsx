import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'

type ToastTone = 'ok' | 'bad' | 'neutral'
interface ToastItem { id: number; tone: ToastTone; text: string }
const ToastContext = createContext<(text: string, tone?: ToastTone) => void>(() => undefined)

export function useToast() { return useContext(ToastContext) }

/** Short messages that confirm an action. They sit in a polite live region so screen readers announce them. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const next = useRef(1)
  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), [])
  const push = useCallback((text: string, tone: ToastTone = 'neutral') => {
    const id = next.current++
    setItems((all) => [...all.slice(-2), { id, tone, text }])
    window.setTimeout(() => dismiss(id), tone === 'bad' ? 9000 : 5000)
  }, [dismiss])
  const value = useMemo(() => push, [push])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite" aria-atomic="false">
        {items.map((t) => {
          const Icon = t.tone === 'ok' ? CheckCircle2 : t.tone === 'bad' ? AlertTriangle : Info
          return (
            <div key={t.id} className={`toast toast-${t.tone}`}>
              <Icon size={18} aria-hidden="true" />
              <span>{t.text}</span>
              <button type="button" className="icon-btn small" onClick={() => dismiss(t.id)}><X size={14} aria-hidden="true" /><span className="visually-hidden">Dismiss</span></button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
