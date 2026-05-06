"use client";

import { useTranslation } from "react-i18next";

const TOOLS = [
  { id: "brainstorm", label: "Brainstorm" },
  { id: "rag", label: "Knowledge Base" },
  { id: "web_search", label: "Web Search" },
  { id: "code_execution", label: "Code Execution" },
  { id: "reason", label: "Deep Reasoning" },
  { id: "paper_search", label: "Paper Search" },
] as const;

interface AdvancedPanelProps {
  hints: string[];
  onHintsChange: (hints: string[]) => void;
}

export function AdvancedPanel({ hints, onHintsChange }: AdvancedPanelProps) {
  const { t } = useTranslation();

  function toggle(toolId: string) {
    onHintsChange(
      hints.includes(toolId)
        ? hints.filter((h) => h !== toolId)
        : [...hints, toolId],
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--secondary)] px-4 py-3">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {t("Tool hints — optional, agent still decides")}
      </p>
      <div className="flex flex-wrap gap-2">
        {TOOLS.map((tool) => {
          const active = hints.includes(tool.id);
          return (
            <button
              key={tool.id}
              type="button"
              onClick={() => toggle(tool.id)}
              className={[
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                active
                  ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
              ].join(" ")}
            >
              {t(tool.label)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
