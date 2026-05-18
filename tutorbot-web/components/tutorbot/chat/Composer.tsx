'use client'

import { useState, KeyboardEvent } from 'react'
import { Send } from 'lucide-react'

export type ComposerProps = {
  onSend: (text: string) => void
  disabled?: boolean
  sending?: boolean
  placeholder?: string
}

export function Composer({ onSend, disabled, sending, placeholder }: ComposerProps) {
  const [text, setText] = useState('')

  function handleSend() {
    const trimmed = text.trim()
    if (!trimmed || disabled || sending) return
    onSend(trimmed)
    setText('')
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="border-t border-[var(--border)] px-5 py-3 shrink-0">
      <div className="mx-auto flex max-w-[720px] items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-[14px] leading-[1.5] placeholder:text-[var(--muted-foreground)]/60 focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
          placeholder={placeholder}
          disabled={disabled || sending}
        />
        <button
          onClick={handleSend}
          disabled={disabled || sending || text.trim().length === 0}
          className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-30"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
