"use client";

import { ChevronDown, ChevronRight, GraduationCap } from "lucide-react";
import { useState } from "react";

import type { LessonPlan, LessonStep } from "@/lib/bot-ws";

interface LessonPlanCardProps {
  plan: LessonPlan;
  className?: string;
}

const PHASE_LABELS: Record<string, string> = {
  assess: "Assess",
  define: "Define",
  explain: "Explain",
  check: "Check",
  adapt: "Adapt",
  wrap_up: "Wrap-up",
};

function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? phase;
}

function statusMark(step: LessonStep): { glyph: string; cls: string; label: string } {
  switch (step.status) {
    case "done":
      return {
        glyph: "✓",
        cls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
        label: "done",
      };
    case "in_progress":
      return {
        glyph: "▶",
        cls: "bg-[var(--primary)]/15 text-[var(--primary)] animate-pulse",
        label: "in progress",
      };
    case "skipped":
      return {
        glyph: "—",
        cls: "bg-[var(--muted)] text-[var(--muted-foreground)]",
        label: "skipped",
      };
    default:
      return {
        glyph: "·",
        cls: "bg-[var(--muted)] text-[var(--muted-foreground)]/60",
        label: "pending",
      };
  }
}

export default function LessonPlanCard({ plan, className = "" }: LessonPlanCardProps) {
  const [open, setOpen] = useState(true);
  const total = plan.steps.length;
  const done = plan.steps.filter((s) => s.status === "done").length;
  const isComplete = done === total && total > 0;

  return (
    <div
      className={`rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-sm ${className}`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-[var(--muted)]/40"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
        )}
        <GraduationCap className="h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
        <span className="flex-1 truncate text-[13px] font-medium text-[var(--foreground)]">
          {plan.topic || "Lesson"}
        </span>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
            isComplete
              ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
              : "bg-[var(--muted)] text-[var(--muted-foreground)]"
          }`}
        >
          {done}/{total}
        </span>
      </button>
      {open && (
        <ol className="space-y-1 border-t border-[var(--border)] px-3 py-2">
          {plan.steps.map((s) => {
            const m = statusMark(s);
            const isCurrent = s.id === plan.current_step_id;
            return (
              <li
                key={s.id}
                className={`flex items-start gap-2 rounded-md px-2 py-1.5 text-[12px] ${
                  isCurrent ? "bg-[var(--primary)]/5" : ""
                }`}
              >
                <span
                  aria-label={m.label}
                  className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${m.cls}`}
                >
                  {m.glyph}
                </span>
                <div className="flex-1 leading-snug">
                  <div className="flex items-center gap-1.5">
                    <span className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                      {phaseLabel(s.phase)}
                    </span>
                    <span
                      className={`${
                        s.status === "done"
                          ? "text-[var(--muted-foreground)]"
                          : "text-[var(--foreground)]"
                      } ${s.status === "done" ? "line-through decoration-[var(--muted-foreground)]/40" : ""}`}
                    >
                      {s.goal}
                    </span>
                  </div>
                  {s.output_summary && s.status === "done" && (
                    <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                      ↳ {s.output_summary}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
