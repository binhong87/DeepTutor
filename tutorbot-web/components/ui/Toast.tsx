'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

type ToastKind = 'error' | 'info' | 'success'

type ToastEntry = {
  id: string
  message: string
  kind: ToastKind
}

type ToastApi = {
  toast: (message: string, opts?: { kind?: ToastKind; durationMs?: number }) => void
}

const ToastContext = createContext<ToastApi | null>(null)

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([])
  const timersRef = useRef<Map<string, number>>(new Map())

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const handle = timersRef.current.get(id)
    if (handle !== undefined) {
      window.clearTimeout(handle)
      timersRef.current.delete(id)
    }
  }, [])

  const toast = useCallback<ToastApi['toast']>((message, opts) => {
    const id = crypto.randomUUID()
    const kind: ToastKind = opts?.kind ?? 'info'
    const durationMs = opts?.durationMs ?? 4000
    setToasts((prev) => [...prev, { id, message, kind }])
    const handle = window.setTimeout(() => dismiss(id), durationMs)
    timersRef.current.set(id, handle)
  }, [dismiss])

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      timers.forEach((handle) => window.clearTimeout(handle))
      timers.clear()
    }
  }, [])

  const api = useMemo<ToastApi>(() => ({ toast }), [toast])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastEntry[]
  onDismiss: (id: string) => void
}) {
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          aria-live="polite"
          style={
            t.kind === 'error'
              ? { background: 'var(--destructive)', color: 'var(--destructive-foreground)' }
              : t.kind === 'success'
              ? { background: 'var(--primary)', color: 'var(--primary-foreground)' }
              : { background: 'var(--card)', color: 'var(--card-foreground)', border: '1px solid var(--border)' }
          }
          className="pointer-events-auto rounded-lg px-4 py-2 shadow-lg text-sm flex items-center gap-2"
        >
          <span>{t.message}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => onDismiss(t.id)}
            className="opacity-70 hover:opacity-100 leading-none"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
