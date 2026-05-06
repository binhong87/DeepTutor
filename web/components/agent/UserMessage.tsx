import type { AgentTurn } from "@/lib/agent-chat-types";

interface UserMessageProps {
  turn: AgentTurn;
}

export function UserMessage({ turn }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-[var(--accent)] px-4 py-2.5 text-sm text-white">
        {turn.userContent}
      </div>
    </div>
  );
}
