'use client'

import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Paperclip } from 'lucide-react'

import type { Attachment } from '../../../lib/agent-chat-types'

const MAX_IMAGE_MB = Number(process.env.NEXT_PUBLIC_MAX_IMAGE_MB ?? 10)
const MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024
const ALLOWED_IMAGE_MIMES = new Set([
  'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml',
])

// Exported so Composer can call it from paste/drop handlers.
export async function processImageFile(
  file: File,
  onAdd: (a: Attachment) => void,
  onError: (msg: string) => void,
  t: (key: string) => string,
): Promise<void> {
  const mime = (file.type || '').toLowerCase()
  if (!ALLOWED_IMAGE_MIMES.has(mime)) {
    onError(t('composer.imageWrongType'))
    return
  }
  if (file.size > MAX_IMAGE_BYTES) {
    onError(t('composer.imageTooLarge'))
    return
  }

  const buffer = await file.arrayBuffer()
  const bytes = new Uint8Array(buffer)

  // SVG XSS guard: refuse SVGs that contain inline scripts.
  if (mime === 'image/svg+xml') {
    const text = new TextDecoder().decode(bytes)
    if (/<script/i.test(text)) {
      onError(t('composer.imageWrongType'))
      return
    }
  }

  const base64 = bytesToBase64(bytes)
  const previewUrl = URL.createObjectURL(file)

  onAdd({
    id: crypto.randomUUID(),
    type: 'image',
    filename: file.name,
    mimeType: mime,
    sizeBytes: file.size,
    base64,
    previewUrl,
  })
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary)
}

export type AttachmentPickerProps = {
  onAdd: (attachment: Attachment) => void
  onError: (message: string) => void
}

export function AttachmentPicker({ onAdd, onError }: AttachmentPickerProps) {
  const { t } = useTranslation('app')
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFile(file: File) {
    await processImageFile(file, onAdd, onError, t)
  }

  function handleClick() {
    inputRef.current?.click()
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handleFile(file)
          e.target.value = ''
        }}
      />
      <button
        type="button"
        onClick={handleClick}
        aria-label={t('composer.attachImage')}
        title={t('composer.attachImage')}
        className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-xl text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)] disabled:opacity-30"
      >
        <Paperclip className="h-4 w-4" />
      </button>
    </>
  )
}
