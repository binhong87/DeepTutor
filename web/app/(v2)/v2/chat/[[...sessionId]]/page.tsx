"use client";

import { useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { MessageFeed } from "@/components/agent/MessageFeed";
import { AgentComposer } from "@/components/agent/AgentComposer";
import { useAgentChat } from "@/context/AgentChatContext";

export default function V2ChatPage() {
  const params = useParams<{ sessionId?: string[] }>();
  const sessionIdParam = params.sessionId?.[0] ?? null;
  const router = useRouter();
  const { session, loadSession, newSession } = useAgentChat();

  // Bridges the one-render gap between calling newSession() and the reducer
  // setting session.sessionId to null. Without this, the URL-push effect (below)
  // sees the stale sessionId in the same render cycle and redirects back.
  const clearingRef = useRef(false);

  // No sessionId in URL → always start a fresh draft
  useEffect(() => {
    if (!sessionIdParam) {
      clearingRef.current = true;
      newSession();
    }
  }, [sessionIdParam, newSession]);

  // Load session when the URL has a sessionId the context doesn't hold yet
  useEffect(() => {
    if (!sessionIdParam) return;
    if (session.sessionId === sessionIdParam) return;
    void loadSession(sessionIdParam);
  }, [sessionIdParam, session.sessionId, loadSession]);

  // Push URL once the server assigns a session ID to a new draft turn.
  // Reset clearingRef when session.sessionId reaches null so the next
  // server-assigned ID can trigger the redirect normally.
  useEffect(() => {
    if (!session.sessionId) {
      clearingRef.current = false;
      return;
    }
    if (sessionIdParam) return;       // URL already correct
    if (clearingRef.current) return;  // still waiting for stale state to clear
    router.replace(`/v2/chat/${session.sessionId}`);
  }, [session.sessionId, sessionIdParam, router]);

  return (
    <div className="flex h-full flex-col">
      <MessageFeed session={session} />
      <AgentComposer />
    </div>
  );
}
