"use client";

import dynamic from "next/dynamic";
import type { RichOutputType } from "@/lib/agent-chat-types";
import type { QuizQuestion } from "@/lib/quiz-types";
import type { MathAnimatorResult } from "@/lib/math-animator-types";
import type { VisualizeResult } from "@/lib/visualize-types";
import type { OutlineItem } from "@/lib/research-types";

// Lazy-load each viewer — all four use default exports
const QuizViewer = dynamic(
  () => import("@/components/quiz/QuizViewer"),
  { ssr: false },
);
const MathAnimatorViewer = dynamic(
  () => import("@/components/math-animator/MathAnimatorViewer"),
  { ssr: false },
);
const VisualizationViewer = dynamic(
  () => import("@/components/visualize/VisualizationViewer"),
  { ssr: false },
);
const ResearchOutlineEditor = dynamic(
  () => import("@/components/research/ResearchOutlineEditor"),
  { ssr: false },
);

interface RichOutputEmbedProps {
  richOutputType: RichOutputType;
  richOutputData: unknown;
  sessionId: string | null;
  turnId: string;
}

type ResearchOutputData = {
  outline?: OutlineItem[];
  topic?: string;
  status?: "editing" | "researching" | "done";
};

export function RichOutputEmbed({
  richOutputType,
  richOutputData,
  sessionId,
  turnId: _turnId,
}: RichOutputEmbedProps) {
  if (!richOutputType || !richOutputData) return null;

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-[var(--accent-subtle,#dbeafe)] dark:border-[#1c3a5e]">
      {richOutputType === "quiz" && (
        <QuizViewer
          questions={richOutputData as QuizQuestion[]}
          sessionId={sessionId}
        />
      )}
      {richOutputType === "math_animator" && (
        <MathAnimatorViewer result={richOutputData as MathAnimatorResult} />
      )}
      {richOutputType === "visualize" && (
        <VisualizationViewer result={richOutputData as VisualizeResult} />
      )}
      {richOutputType === "deep_research" && (() => {
        const d = richOutputData as ResearchOutputData;
        return (
          <ResearchOutlineEditor
            outline={d?.outline ?? []}
            topic={d?.topic ?? ""}
            onConfirm={() => {}}
            status={d?.status ?? "done"}
          />
        );
      })()}
    </div>
  );
}
