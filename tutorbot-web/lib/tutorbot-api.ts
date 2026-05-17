import { apiUrl, apiFetch } from "./api";

// ── Types ────────────────────────────────────────────────────────

export interface TutorBotSummary {
  bot_id: string;
  name: string;
  description: string;
  running: boolean;
  started_at: string | null;
  last_reload_error: string | null;
  channels?: Record<string, unknown>;
  model?: string | null;
  persona: string;
}

export interface TutorBotDetail extends TutorBotSummary {
  llm_selection?: Record<string, string> | null;
}

export interface Soul {
  id: string;
  name: string;
  content: string;
}

export interface ChannelSchemaInfo {
  name: string;
  display_name: string;
  default_config: Record<string, unknown>;
  secret_fields: string[];
  json_schema: Record<string, unknown>;
}

export interface ChannelSchemas {
  channels: Record<string, ChannelSchemaInfo>;
  global: { json_schema: Record<string, unknown>; secret_fields: string[] };
}

export interface BotWorkspaceFile {
  filename: string;
  content: string;
}

export interface CreateBotPayload {
  bot_id: string;
  name?: string;
  description?: string;
  persona?: string;
  channels?: Record<string, unknown>;
  model?: string;
  llm_selection?: Record<string, string>;
}

export interface UpdateBotPayload {
  name?: string;
  description?: string;
  persona?: string;
  channels?: Record<string, unknown>;
  model?: string;
  llm_selection?: Record<string, string>;
}

// ── API functions ─────────────────────────────────────────────────

function url(path: string) {
  return apiUrl(`/api/v1/tutorbot${path}`);
}

// Bots

export async function listBots(): Promise<TutorBotSummary[]> {
  return apiFetch(url("")).then(r => r.json());
}

export async function getRecentBots(limit = 3): Promise<TutorBotSummary[]> {
  return apiFetch(url(`/recent?limit=${limit}`)).then(r => r.json());
}

export async function getBot(botId: string, includeSecrets = false): Promise<TutorBotDetail> {
  const qs = includeSecrets ? "?include_secrets=true" : "";
  return apiFetch(url(`/${botId}${qs}`)).then(r => r.json());
}

export async function createBot(payload: CreateBotPayload): Promise<TutorBotDetail> {
  return apiFetch(url(""), {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(r => r.json());
}

export async function updateBot(botId: string, payload: UpdateBotPayload): Promise<TutorBotDetail> {
  return apiFetch(url(`/${botId}`), {
    method: "PATCH",
    body: JSON.stringify(payload),
  }).then(r => r.json());
}

export async function stopBot(botId: string): Promise<{ bot_id: string; stopped: boolean }> {
  return apiFetch(url(`/${botId}`), { method: "DELETE" }).then(r => r.json());
}

export async function destroyBot(botId: string): Promise<{ bot_id: string; destroyed: boolean }> {
  return apiFetch(url(`/${botId}/destroy`), { method: "DELETE" }).then(r => r.json());
}

// Workspace files

export async function listBotFiles(botId: string): Promise<BotWorkspaceFile[]> {
  return apiFetch(url(`/${botId}/files`)).then(r => r.json());
}

export async function readBotFile(botId: string, filename: string): Promise<BotWorkspaceFile> {
  return apiFetch(url(`/${botId}/files/${filename}`)).then(r => r.json());
}

export async function writeBotFile(botId: string, filename: string, content: string): Promise<{ filename: string; saved: boolean }> {
  return apiFetch(url(`/${botId}/files/${filename}`), {
    method: "PUT",
    body: JSON.stringify({ content }),
  }).then(r => r.json());
}

// Chat history

export async function getBotHistory(botId: string, limit = 100): Promise<unknown[]> {
  return apiFetch(url(`/${botId}/history?limit=${limit}`)).then(r => r.json());
}

// Souls

export async function listSouls(): Promise<Soul[]> {
  return apiFetch(url("/souls")).then(r => r.json());
}

export async function getSoul(soulId: string): Promise<Soul> {
  return apiFetch(url(`/souls/${soulId}`)).then(r => r.json());
}

export async function createSoul(id: string, name: string, content: string): Promise<Soul> {
  return apiFetch(url("/souls"), {
    method: "POST",
    body: JSON.stringify({ id, name, content }),
  }).then(r => r.json());
}

export async function updateSoul(soulId: string, name?: string, content?: string): Promise<Soul> {
  return apiFetch(url(`/souls/${soulId}`), {
    method: "PUT",
    body: JSON.stringify({ name, content }),
  }).then(r => r.json());
}

export async function deleteSoul(soulId: string): Promise<{ id: string; deleted: boolean }> {
  return apiFetch(url(`/souls/${soulId}`), { method: "DELETE" }).then(r => r.json());
}

// Channel schemas

export async function getChannelSchemas(): Promise<ChannelSchemas> {
  return apiFetch(url("/channels/schema")).then(r => r.json());
}

// ── Sessions ─────────────────────────────────────────────────────

export interface LessonPlanBrief {
  topic: string;
  current_step_id: string | null;
  total_steps: number;
  done_steps: number;
}

export type SessionStatus = "default" | "active" | "completed" | "archived";

export interface SessionRow {
  id: string;
  title: string;
  title_source: "lesson_plan" | "manual" | "auto" | null;
  status: SessionStatus;
  updated_at: string;
  has_user_messages: boolean;
  lesson_plan_brief: LessonPlanBrief | null;
}

export interface BotTreeRow {
  bot_id: string;
  name: string;
  running: boolean;
  sessions: SessionRow[];
}

export async function listBotSessions(botId: string): Promise<SessionRow[]> {
  return apiFetch(url(`/${botId}/sessions`)).then(r => r.json());
}

/** Returns the new default session, or throws an Error with .code = 409
 *  carrying `{ existing_default_id }` when the current default is empty. */
export async function createBotSession(botId: string): Promise<SessionRow> {
  const res = await apiFetch(url(`/${botId}/sessions`), { method: "POST" });
  if (res.status === 409) {
    const body = await res.json();
    const err = new Error("default-session-empty") as Error & { code: number; data: unknown };
    err.code = 409;
    err.data = body.detail;
    throw err;
  }
  return res.json();
}

export async function getBotSessionHistory(
  botId: string, sessionId: string, limit = 100,
): Promise<{ role: string; content: string }[]> {
  return apiFetch(url(`/${botId}/sessions/${sessionId}/history?limit=${limit}`)).then(r => r.json());
}

export async function getTutorbotTree(): Promise<BotTreeRow[]> {
  return apiFetch(url(`/tree`)).then(r => r.json());
}
