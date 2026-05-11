"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { BookOpen, Plus, Loader2, FileText, Trash2, AlertTriangle } from "lucide-react";
import { listKnowledgeBases, deleteKnowledgeBase, type KnowledgeBaseInfo } from "@/lib/knowledge-api";
import { useTranslation } from "react-i18next";

function KbStatusBadge({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation();
  const config: Record<string, { label: string; color: string }> = {
    ready: { label: t("Ready"), color: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400" },
    initializing: { label: t("Indexing"), color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400" },
    error: { label: "Error", color: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400" },
  };
  const s = config[status ?? ""] ?? { label: status ?? t("Unknown"), color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${s.color}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${
        status === "ready" ? "bg-green-500" : status === "initializing" ? "bg-yellow-500" : status === "error" ? "bg-red-500" : "bg-gray-400"
      }`} />
      {s.label}
    </span>
  );
}

export default function KnowledgePage() {
  const [kbs, setKbs] = useState<KnowledgeBaseInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { t } = useTranslation();

  async function refresh() {
    try {
      setError("");
      const list = await listKnowledgeBases();
      setKbs(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load knowledge bases"));
    }
  }

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, []);

  async function handleDelete(name: string) {
    try {
      await deleteKnowledgeBase(name);
      setKbs(prev => prev.filter(kb => kb.name !== name));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to delete knowledge base"));
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--foreground)]">{t("Knowledge Bases")}</h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {t("Upload documents and create searchable knowledge bases for your bots.")}
          </p>
        </div>
        <Link
          href="/knowledge/create"
          className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 transition-opacity"
        >
          <Plus className="h-4 w-4" />
          {t("New Knowledge Base")}
        </Link>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400 mb-6">
          {error}
        </div>
      )}

      {kbs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-12 text-center">
          <BookOpen className="mx-auto h-12 w-12 text-[var(--muted-foreground)]/50" />
          <h2 className="mt-4 text-lg font-medium text-[var(--foreground)]">{t("No knowledge bases yet")}</h2>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {t("Upload PDFs, documents, and text files to build searchable knowledge bases.")}
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {kbs.map(kb => (
            <div key={kb.name} className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-5 hover:shadow-sm transition-shadow">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--primary)]/10">
                    <BookOpen className="h-5 w-5 text-[var(--primary)]" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-[var(--foreground)]">{kb.name}</h3>
                      {kb.is_default && (
                        <span className="rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-xs font-medium text-[var(--primary)]">
                          {t("Default")}
                        </span>
                      )}
                      {kb.read_only && (
                        <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs text-[var(--muted-foreground)]">
                          {t("Read-only")}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <KbStatusBadge status={kb.status} />
                      <span className="text-xs text-[var(--muted-foreground)]">
                        <FileText className="inline h-3 w-3 mr-0.5" />
                        {kb.statistics?.raw_documents ?? 0} {t("documents")}
                      </span>
                      {kb.provenance_label && (
                        <span className="text-xs text-[var(--muted-foreground)]">{kb.provenance_label}</span>
                      )}
                    </div>
                  </div>
                </div>
                {!kb.read_only && (
                  <button
                    onClick={() => handleDelete(kb.name)}
                    className="p-1.5 rounded-md text-[var(--muted-foreground)] hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition-colors"
                    title="Delete knowledge base"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
              {kb.progress && kb.progress.stage && kb.progress.stage !== "completed" && (
                <div className="mt-3 pt-3 border-t border-[var(--border)]">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 rounded-full bg-[var(--muted)] overflow-hidden">
                      <div
                        className="h-full rounded-full bg-[var(--primary)] transition-all duration-500"
                        style={{ width: `${kb.progress.percent ?? 0}%` }}
                      />
                    </div>
                    <span className="text-xs text-[var(--muted-foreground)]">{kb.progress.percent ?? 0}%</span>
                  </div>
                  <p className="text-xs text-[var(--muted-foreground)] mt-1">{kb.progress.message}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
