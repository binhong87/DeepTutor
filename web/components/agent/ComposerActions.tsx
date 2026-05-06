"use client";

import { useTranslation } from "react-i18next";
import { BookOpen, Settings2, Square } from "lucide-react";
import type { AgentLLMSelection } from "@/lib/agent-chat-types";

// KnowledgeBaseSummary is the actual exported type from knowledge-api.ts.
// It uses `name` as its primary identifier — there is no separate `id` field.
import type { KnowledgeBaseSummary } from "@/lib/knowledge-api";

interface ComposerActionsProps {
  knowledgeBases: KnowledgeBaseSummary[];
  activeKbId: string | null;
  llmSelection: AgentLLMSelection | null;
  hints: string[];
  advancedOpen: boolean;
  isStreaming: boolean;
  onKbChange: (id: string | null) => void;
  onAdvancedToggle: () => void;
  onSend: () => void;
  onCancel: () => void;
}

export function ComposerActions({
  knowledgeBases,
  activeKbId,
  hints,
  advancedOpen,
  isStreaming,
  onKbChange,
  onAdvancedToggle,
  onSend,
  onCancel,
}: ComposerActionsProps) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {/* KB selector */}
        <label className="relative flex items-center">
          <BookOpen
            size={10}
            className="pointer-events-none absolute left-2 text-[var(--muted-foreground)]"
          />
          <select
            className="appearance-none rounded-full border border-[var(--border)] bg-[var(--secondary)] py-1 pl-5 pr-3 text-xs text-[var(--foreground)] cursor-pointer hover:bg-[var(--muted)] focus:outline-none"
            value={activeKbId ?? ""}
            onChange={(e) => onKbChange(e.target.value || null)}
            aria-label={t("Knowledge Base")}
          >
            <option value="">{t("KB: None")}</option>
            {knowledgeBases.map((kb) => (
              <option key={kb.name} value={kb.name}>
                {kb.name}
              </option>
            ))}
          </select>
        </label>

        {/* Advanced toggle */}
        <button
          type="button"
          onClick={onAdvancedToggle}
          className={[
            "flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors",
            advancedOpen || hints.length > 0
              ? "border border-[var(--primary)] bg-[var(--secondary)] text-[var(--primary)]"
              : "border border-[var(--border)] bg-[var(--secondary)] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
          ].join(" ")}
        >
          <Settings2 size={10} />
          {t("Advanced")}
          {hints.length > 0 && (
            <span className="ml-0.5 text-[10px]">({hints.length})</span>
          )}
        </button>
      </div>

      {/* Send / Cancel */}
      {isStreaming ? (
        <button
          type="button"
          onClick={onCancel}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-500 text-white hover:bg-red-600"
          aria-label={t("Cancel")}
        >
          <Square size={13} fill="white" />
        </button>
      ) : (
        <button
          type="button"
          onClick={onSend}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-white hover:opacity-90"
          aria-label={t("Send")}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </button>
      )}
    </div>
  );
}
