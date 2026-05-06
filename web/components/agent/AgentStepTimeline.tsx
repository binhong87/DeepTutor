"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Zap } from "lucide-react";
import type { StepEvent } from "@/lib/agent-chat-types";

const STEP_ICON: Record<string, string> = {
  thinking: "🧠",
  tool_call: "🔧",
  tool_result: "✓",
  stage_start: "▶",
  stage_end: "■",
  observation: "👁",
};

interface AgentStepTimelineProps {
  steps: StepEvent[];
  isStreaming: boolean;
}

export function AgentStepTimeline({ steps, isStreaming }: AgentStepTimelineProps) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0 && !isStreaming) return null;

  // Collect unique tool names from tool_call steps for the summary line
  const toolsUsed = [
    ...new Set(
      steps
        .filter((s) => s.type === "tool_call")
        .map((s) => s.label.split(":")[0].trim()),
    ),
  ];

  // Collapsed summary (shown once streaming ends)
  if (!isStreaming && steps.length > 0) {
    return (
      <div className="mb-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
        >
          <Zap size={11} className="text-[var(--accent)]" />
          <span>
            {toolsUsed.length > 0
              ? `Used ${toolsUsed.join(" · ")}`
              : `${steps.length} step${steps.length !== 1 ? "s" : ""}`}
          </span>
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </button>
        {expanded && (
          <div className="mt-2 space-y-1 pl-4 border-l border-[var(--border)]">
            {steps.map((step) => <StepRow key={step.id} step={step} />)}
          </div>
        )}
      </div>
    );
  }

  // Live view during streaming
  return (
    <div className="mb-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="space-y-1.5">
        {steps.map((step, i) => (
          <StepRow
            key={step.id}
            step={step}
            isActive={i === steps.length - 1 && isStreaming}
          />
        ))}
        {isStreaming && steps.length === 0 && (
          <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent)]" />
            Thinking…
          </div>
        )}
      </div>
    </div>
  );
}

function StepRow({ step, isActive }: { step: StepEvent; isActive?: boolean }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="mt-0.5 shrink-0 text-[11px]">
        {isActive ? (
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent)]" />
        ) : (
          STEP_ICON[step.type] ?? "·"
        )}
      </span>
      <span className={step.done ? "text-[var(--muted)]" : "text-[var(--foreground)]"}>
        {step.label}
      </span>
    </div>
  );
}
