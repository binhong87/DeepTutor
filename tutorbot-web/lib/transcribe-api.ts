import { apiUrl, apiFetch } from "@/lib/api";

export type TranscribeResult = {
  transcript: string;
  language?: string;
  durationMs?: number;
};

export class TranscribeError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "TranscribeError";
  }
}

/**
 * Transcribe audio blob to text via /api/v1/transcribe
 * @param blob Audio blob to transcribe
 * @param opts Optional language hint and abort signal for cancellation
 * @returns Transcript, language, and duration
 */
export async function transcribe(
  blob: Blob,
  opts?: { language?: string; signal?: AbortSignal },
): Promise<TranscribeResult> {
  const form = new FormData();
  form.append("file", blob, `voice.${extFromMime(blob.type)}`);
  if (opts?.language) form.append("language", opts.language);

  const resp = await apiFetch(apiUrl("/api/v1/transcribe"), {
    method: "POST",
    body: form,
    signal: opts?.signal,
  });

  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new TranscribeError(resp.status, body || `HTTP ${resp.status}`);
  }

  const json = (await resp.json()) as {
    transcript: string;
    language?: string | null;
    duration_ms?: number | null;
  };

  return {
    transcript: json.transcript,
    language: json.language ?? undefined,
    durationMs: json.duration_ms ?? undefined,
  };
}

/**
 * Map MIME type to file extension for FormData filename
 */
function extFromMime(mime: string): string {
  const m = mime.toLowerCase();
  if (m.includes("webm")) return "webm";
  if (m.includes("mp4")) return "m4a";
  if (m.includes("wav")) return "wav";
  if (m.includes("mpeg") || m.includes("mp3")) return "mp3";
  return "bin";
}
