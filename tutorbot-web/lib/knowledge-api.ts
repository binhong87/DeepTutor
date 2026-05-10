import { apiUrl, apiFetch } from "./api";

// ── Types ────────────────────────────────────────────────────────

export interface KnowledgeBaseInfo {
  id: string | null;
  name: string;
  is_default: boolean;
  statistics: {
    raw_documents?: number;
    images?: number;
    content_lists?: number;
    rag_initialized?: boolean;
  };
  metadata?: Record<string, unknown> | null;
  path?: string | null;
  status?: string | null;
  progress?: {
    stage: string;
    message: string;
    percent: number;
    current: number;
    total: number;
    task_id?: string;
    timestamp?: string;
    indexed_count?: number;
    index_changed?: boolean;
    index_action?: string;
  } | null;
  source?: string | null;
  assigned?: boolean;
  read_only?: boolean;
  provenance_label?: string | null;
  available?: boolean;
}

export interface KbFileInfo {
  name: string;
  size: number;
  modified: number;
  mime_type: string | null;
}

export interface SupportedFileTypes {
  extensions: string[];
  accept: string;
  max_file_size_bytes: number;
  max_pdf_size_bytes: number;
}

export interface UploadResult {
  message: string;
  files: string[];
  task_id: string;
}

// ── API functions ─────────────────────────────────────────────────

function url(path: string) {
  return apiUrl(`/api/v1/knowledge${path}`);
}

// List & CRUD

export async function listKnowledgeBases(): Promise<KnowledgeBaseInfo[]> {
  return apiFetch(url("/list")).then(r => r.json());
}

export async function getKnowledgeBase(name: string): Promise<KnowledgeBaseInfo> {
  return apiFetch(url(`/${encodeURIComponent(name)}`)).then(r => r.json());
}

export async function createKnowledgeBase(
  name: string,
  files: File[],
): Promise<UploadResult> {
  const form = new FormData();
  form.append("name", name);
  files.forEach(f => form.append("files", f));
  return apiFetch(url("/create"), { method: "POST", body: form }).then(r => r.json());
}

export async function deleteKnowledgeBase(name: string): Promise<{ message: string }> {
  return apiFetch(url(`/${encodeURIComponent(name)}`), { method: "DELETE" }).then(r => r.json());
}

// Files

export async function listKbFiles(kbName: string): Promise<{ files: KbFileInfo[] }> {
  return apiFetch(url(`/${encodeURIComponent(kbName)}/files`)).then(r => r.json());
}

export function kbFileUrl(kbName: string, filename: string): string {
  return url(`/${encodeURIComponent(kbName)}/files/${encodeURIComponent(filename)}`);
}

// Upload

export async function uploadFiles(kbName: string, files: File[]): Promise<UploadResult> {
  const form = new FormData();
  files.forEach(f => form.append("files", f));
  return apiFetch(url(`/${encodeURIComponent(kbName)}/upload`), {
    method: "POST",
    body: form,
  }).then(r => r.json());
}

// Reindex

export async function reindexKnowledgeBase(
  name: string,
): Promise<{ message: string; task_id: string | null; noop: boolean }> {
  return apiFetch(url(`/${encodeURIComponent(name)}/reindex`), { method: "POST" }).then(r => r.json());
}

// Progress

export async function getProgress(name: string): Promise<{
  status: string;
  message: string;
  stage?: string;
  percent?: number;
}> {
  return apiFetch(url(`/${encodeURIComponent(name)}/progress`)).then(r => r.json());
}

// Default

export async function setDefaultKb(name: string): Promise<{ default_kb: string }> {
  return apiFetch(url(`/default/${encodeURIComponent(name)}`), { method: "PUT" }).then(r => r.json());
}

export async function getDefaultKb(): Promise<{ default_kb: string | null }> {
  return apiFetch(url("/default")).then(r => r.json());
}

// Supported file types

export async function getSupportedFileTypes(): Promise<SupportedFileTypes> {
  return apiFetch(url("/supported-file-types")).then(r => r.json());
}
