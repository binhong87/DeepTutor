'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Mic, Square } from 'lucide-react'

import { transcribe, TranscribeError } from '../../../lib/transcribe-api'

const MAX_RECORDING_MS = 60_000
const PREFERRED_MIMES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
] as const

function writeStr(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
}

async function convertToWav(blob: Blob): Promise<Blob> {
  const arrayBuffer = await blob.arrayBuffer()
  const audioCtx = new AudioContext()
  const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer)
  await audioCtx.close()

  const sampleRate = audioBuffer.sampleRate
  const samples = audioBuffer.getChannelData(0) // mono
  const wav = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(wav)

  writeStr(v, 0, 'RIFF')
  v.setUint32(4, 36 + samples.length * 2, true)
  writeStr(v, 8, 'WAVE')
  writeStr(v, 12, 'fmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true)           // PCM
  v.setUint16(22, 1, true)           // mono
  v.setUint32(24, sampleRate, true)
  v.setUint32(28, sampleRate * 2, true)
  v.setUint16(32, 2, true)
  v.setUint16(34, 16, true)
  writeStr(v, 36, 'data')
  v.setUint32(40, samples.length * 2, true)

  let off = 44
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    off += 2
  }

  return new Blob([wav], { type: 'audio/wav' })
}

export type MicButtonProps = {
  onTranscribed: (transcript: string, blob: Blob, mimeType: string, durationMs: number) => void
  onError: (msg: string) => void
  disabled?: boolean
  language?: string
}

type MicState =
  | { kind: 'idle' }
  | { kind: 'requesting' }
  | { kind: 'recording'; startedAt: number; recorder: MediaRecorder; chunks: Blob[]; stream: MediaStream }
  | { kind: 'uploading' }
  | { kind: 'denied' }

function pickMime(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined
  for (const m of PREFERRED_MIMES) {
    if (MediaRecorder.isTypeSupported(m)) return m
  }
  return undefined
}

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function MicButton({ onTranscribed, onError, disabled, language }: MicButtonProps) {
  const { t } = useTranslation('app')
  const [state, setState] = useState<MicState>({ kind: 'idle' })
  const stopTimerRef = useRef<number | null>(null)
  const elapsedRef = useRef<number>(0)
  const [elapsed, setElapsed] = useState(0)

  // navigator.mediaDevices is undefined on insecure origins (non-HTTPS, non-localhost),
  // and on older browsers. Detect after mount to avoid SSR/hydration mismatch.
  const [supported, setSupported] = useState(true)
  useEffect(() => {
    setSupported(
      typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
    )
  }, [])

  // Ref-based cleanup to avoid stale closure bug (state may have changed by unmount time)
  const activeRecordingRef = useRef<{ recorder: MediaRecorder; stream: MediaStream } | null>(null)

  // Tick elapsed counter while recording
  useEffect(() => {
    if (state.kind !== 'recording') return
    const id = window.setInterval(() => {
      const ms = Date.now() - state.startedAt
      elapsedRef.current = ms
      setElapsed(ms)
    }, 200)
    return () => window.clearInterval(id)
  }, [state])

  // Cleanup on unmount: stop active recording, release timer
  useEffect(() => {
    return () => {
      if (stopTimerRef.current) window.clearTimeout(stopTimerRef.current)
      const active = activeRecordingRef.current
      if (active) {
        try { active.recorder.stop() } catch { /* ignore */ }
        active.stream.getTracks().forEach((tr) => tr.stop())
      }
    }
  }, [])

  async function uploadAndHandOff(blob: Blob, mimeType: string, durationMs: number) {
    try {
      const result = await transcribe(blob, { language })
      if (!result.transcript.trim()) {
        onError(t('composer.noSpeechDetected'))
        setState({ kind: 'idle' })
        setElapsed(0)
        return
      }
      onTranscribed(result.transcript, blob, mimeType, durationMs)
    } catch (err) {
      if (err instanceof TranscribeError) {
        onError(t('composer.transcribeFailedWithStatus', { status: err.status }))
      } else {
        onError(t('composer.transcribeFailed'))
      }
    } finally {
      setState({ kind: 'idle' })
      setElapsed(0)
    }
  }

  async function startRecording() {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      // Button should be disabled in this case (see `supported` above), but
      // guard at click time too in case detection raced with a click.
      onError(t('composer.micUnavailable'))
      return
    }
    setState({ kind: 'requesting' })
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = pickMime()
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const chunks: Blob[] = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      recorder.onstop = async () => {
        const rawBlob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
        stream.getTracks().forEach((tr) => tr.stop())
        activeRecordingRef.current = null
        let uploadBlob: Blob = rawBlob
        let uploadMime = recorder.mimeType || 'audio/webm'
        try {
          uploadBlob = await convertToWav(rawBlob)
          uploadMime = 'audio/wav'
        } catch {
          // fall back to original format
        }
        void uploadAndHandOff(uploadBlob, uploadMime, elapsedRef.current)
      }
      stopTimerRef.current = window.setTimeout(() => {
        if (recorder.state === 'recording') {
          onError(t('composer.recordingTooLong'))
          try { recorder.stop() } catch { /* ignore */ }
        }
      }, MAX_RECORDING_MS)
      recorder.start()
      // Track active recording via ref for safe unmount cleanup
      activeRecordingRef.current = { recorder, stream }
      setState({ kind: 'recording', startedAt: Date.now(), recorder, chunks, stream })
    } catch {
      setState({ kind: 'denied' })
      onError(t('composer.micDenied'))
    }
  }

  function stopRecording() {
    if (state.kind !== 'recording') return
    if (stopTimerRef.current) {
      window.clearTimeout(stopTimerRef.current)
      stopTimerRef.current = null
    }
    try { state.recorder.stop() } catch { /* ignore */ }
    setState({ kind: 'uploading' })
  }

  function handleClick() {
    if (disabled) return
    if (state.kind === 'idle' || state.kind === 'denied') {
      void startRecording()
    } else if (state.kind === 'recording') {
      stopRecording()
    }
  }

  const isRecording = state.kind === 'recording'
  const isBusy = state.kind === 'requesting' || state.kind === 'uploading'

  const label = !supported
    ? t('composer.micUnavailable')
    : isRecording
      ? t('composer.stopRecording')
      : t('composer.recordVoice')

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || isBusy || !supported}
      aria-label={label}
      title={label}
      className={[
        'flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-xl transition-colors',
        'disabled:opacity-30',
        isRecording
          ? 'text-red-600 animate-pulse hover:bg-[var(--accent)] hover:text-red-700'
          : 'text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]',
      ].join(' ')}
    >
      {isRecording ? (
        <span className="flex items-center gap-1">
          <Square className="h-4 w-4 fill-current" />
          <span className="text-xs tabular-nums">{formatElapsed(elapsed)}</span>
        </span>
      ) : (
        <Mic className="h-4 w-4" />
      )}
    </button>
  )
}
