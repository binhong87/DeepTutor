"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { AgentSession } from "@/lib/agent-chat-types";
import { UserMessage } from "@/components/agent/UserMessage";
import { AgentMessage } from "@/components/agent/AgentMessage";

interface MessageFeedProps {
  session: AgentSession;
}

export function MessageFeed({ session }: MessageFeedProps) {
  const { t } = useTranslation();
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevTurnsLength = useRef(session.turns.length);

  // Scroll when a new turn is added (smooth) or when steps arrive during streaming (instant to avoid jitter)
  useEffect(() => {
    const isNewTurn = session.turns.length !== prevTurnsLength.current;
    prevTurnsLength.current = session.turns.length;
    bottomRef.current?.scrollIntoView({ behavior: isNewTurn ? "smooth" : "instant" });
  }, [session.turns.length, session.activeSteps.length]);

  if (session.turns.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
        <p className="text-lg font-medium text-[var(--foreground)]">
          {t("Ask anything — I'll use the right tools")}
        </p>
        <p className="text-sm text-[var(--muted)]">
          {t("Search the web, query knowledge bases, run code, or generate quizzes and animations — automatically.")}
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="mx-auto flex max-w-[760px] flex-col gap-8">
        {session.turns.map((turn) => (
          <div key={turn.id} className="flex flex-col gap-4">
            <UserMessage turn={turn} />
            <AgentMessage
              turn={turn}
              activeSteps={session.activeSteps}
              isStreaming={session.isStreaming}
              sessionId={session.sessionId}
            />
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
