"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { MessageFeed } from "@/components/agent/MessageFeed";
import { AgentComposer } from "@/components/agent/AgentComposer";
import { useAgentChat } from "@/context/AgentChatContext";

export default function V2ChatPage() {
  const params = useParams<{ sessionId?: string[] }>();
  const sessionIdParam = params.sessionId?.[0] ?? null;
  const router = useRouter();
  const { session, loadSession } = useAgentChat();

  // Load session from URL on mount / when URL param changes
  useEffect(() => {
    if (!sessionIdParam) return;
    if (session.sessionId === sessionIdParam) return;
    void loadSession(sessionIdParam);
  }, [sessionIdParam, session.sessionId, loadSession]);

  // Push URL once server assigns a session ID to a new draft turn
  useEffect(() => {
    if (!session.sessionId) return;
    if (sessionIdParam === session.sessionId) return;
    router.replace(`/v2/chat/${session.sessionId}`);
  }, [session.sessionId, sessionIdParam, router]);

  return (
    <div className="flex h-full flex-col">
      <MessageFeed session={session} />
      <AgentComposer />
    </div>
  );
}
