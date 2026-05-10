import type { AgentTurn, StepEvent } from "@/lib/agent-chat-types";
import { AgentStepTimeline } from "@/components/shared/AgentStepTimeline";
import AssistantResponse from "@/components/shared/AssistantResponse";
import { RichOutputEmbed } from "@/components/shared/RichOutputEmbed";

interface AgentMessageProps {
  turn: AgentTurn;
  activeSteps: StepEvent[];
  isStreaming: boolean;
  sessionId: string | null;
}

export function AgentMessage({ turn, activeSteps, isStreaming, sessionId }: AgentMessageProps) {
  const steps = turn.status === "streaming" ? activeSteps : turn.steps;
  const showTimeline = steps.length > 0 || (turn.status === "streaming" && isStreaming);

  return (
    <div className="flex flex-col gap-1">
      {showTimeline && (
        <AgentStepTimeline
          steps={steps}
          isStreaming={turn.status === "streaming" && isStreaming}
        />
      )}

      {turn.assistantContent && (
        <div className="rounded-2xl rounded-tl-sm bg-[var(--surface)] px-4 py-3 text-sm text-[var(--foreground)]">
          <AssistantResponse content={turn.assistantContent} />
        </div>
      )}

      {turn.richOutputType && (
        <RichOutputEmbed
          richOutputType={turn.richOutputType}
          richOutputData={turn.richOutputData}
          sessionId={sessionId}
          turnId={turn.id}
        />
      )}

      {turn.status === "error" && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600 dark:bg-red-950 dark:text-red-400">
          {turn.errorMessage ?? "Something went wrong. Please try again."}
        </div>
      )}
    </div>
  );
}
