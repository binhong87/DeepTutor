'use client'

import { useState, KeyboardEvent, ClipboardEvent, DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Send } from 'lucide-react'
import { AttachmentChipRow } from './AttachmentChipRow'
import { AttachmentPicker, processImageFile } from './AttachmentPicker'
import { MicButton } from './MicButton'
import type { Attachment } from '../../../lib/agent-chat-types'

async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary)
}

function extFromMime(mime: string): string {
  const m = (mime || '').toLowerCase()
  if (m.includes('webm')) return 'webm'
  if (m.includes('mp4')) return 'm4a'
  if (m.includes('wav')) return 'wav'
  if (m.includes('mpeg') || m.includes('mp3')) return 'mp3'
  return 'bin'
}

export type ComposerProps = {
  onSend: (text: string, attachments: Attachment[]) => void
  disabled?: boolean
  sending?: boolean
  placeholder?: string
}

export function Composer({ onSend, disabled, sending, placeholder }: ComposerProps) {
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const { t } = useTranslation('app')

  function removeAttachment(id: string) {
    setAttachments((prev) => {
      const target = prev.find((a) => a.id === id)
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl)
      if (target?.objectUrl) URL.revokeObjectURL(target.objectUrl)
      return prev.filter((a) => a.id !== id)
    })
  }

  function addAttachment(a: Attachment) {
    setAttachments((prev) => [...prev, a])
  }

  function showError(msg: string) {
    alert(msg)
  }

  function handleVoiceTranscribed(transcript: string, blob: Blob, mimeType: string, durationMs: number) {
    // STT-M1 merge rule: empty input → replace; non-empty → append with space
    setText((prev) => (prev.trim() ? `${prev} ${transcript}` : transcript))
    void blobToBase64(blob).then((base64) => {
      addAttachment({
        id: crypto.randomUUID(),
        type: 'audio',
        filename: `voice.${extFromMime(mimeType)}`,
        mimeType,
        sizeBytes: blob.size,
        base64,
        durationMs,
        objectUrl: URL.createObjectURL(blob),
      })
    })
  }

  function handleSend() {
    const trimmed = text.trim()
    if ((!trimmed && attachments.length === 0) || disabled || sending) return
    onSend(trimmed, attachments)
    setText('')
    attachments.forEach((a) => {
      if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
      if (a.objectUrl) URL.revokeObjectURL(a.objectUrl)
    })
    setAttachments([])
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  async function handlePaste(e: ClipboardEvent<HTMLDivElement>) {
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file && file.type.startsWith('image/')) {
          e.preventDefault()
          await processImageFile(file, addAttachment, showError, t)
        }
      }
    }
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(true)
  }

  function handleDragLeave(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(false)
  }

  async function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(false)
    for (const file of Array.from(e.dataTransfer.files)) {
      if (file.type.startsWith('image/')) {
        await processImageFile(file, addAttachment, showError, t)
      }
    }
  }

  return (
    <div
      onPaste={handlePaste}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`border-t border-[var(--border)] px-5 py-3 shrink-0${isDragging ? ' border-2 border-dashed border-blue-500' : ''}`}
    >
      <AttachmentChipRow attachments={attachments} onRemove={removeAttachment} />
      <div className="mx-auto flex max-w-[720px] items-end gap-2">
        <AttachmentPicker onAdd={addAttachment} onError={showError} />
        <MicButton
          onTranscribed={handleVoiceTranscribed}
          onError={showError}
          disabled={disabled}
          language={typeof navigator !== 'undefined' ? navigator.language?.split('-')?.[0] : undefined}
        />
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
          disabled={disabled || sending || (text.trim().length === 0 && attachments.length === 0)}
          className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-30"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
