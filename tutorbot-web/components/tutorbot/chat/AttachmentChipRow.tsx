'use client'

import type { Attachment } from '../../../lib/agent-chat-types'

export type AttachmentChipRowProps = {
  attachments: Attachment[]
  onRemove: (id: string) => void
}

export function AttachmentChipRow({ attachments, onRemove }: AttachmentChipRowProps) {
  if (attachments.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2 px-2 pb-2">
      {attachments.map((a) => (
        <div
          key={a.id}
          className="flex items-center gap-2 rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[13px]"
        >
          {a.type === 'image' && a.previewUrl && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={a.previewUrl} alt={a.filename} className="h-8 w-8 object-cover rounded" />
          )}
          {a.type === 'audio' && (
            <>
              <span aria-hidden>🎤</span>
              {a.objectUrl && <audio src={a.objectUrl} controls className="h-6" />}
              <span>{formatDuration(a.durationMs)}</span>
            </>
          )}
          <span className="max-w-[10rem] truncate">{a.filename}</span>
          <button
            type="button"
            onClick={() => onRemove(a.id)}
            aria-label={`Remove ${a.filename}`}
            className="text-[var(--muted-foreground)] hover:text-red-600"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}

function formatDuration(ms: number | undefined): string {
  if (!ms) return ''
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
