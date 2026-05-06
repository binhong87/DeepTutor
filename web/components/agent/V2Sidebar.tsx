"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { SidebarShell } from "@/components/sidebar/SidebarShell";
import { useAgentChat } from "@/context/AgentChatContext";
import {
  deleteSession,
  listSessions,
  updateSessionTitle,
  type SessionSummary,
} from "@/lib/session-api";

export function V2Sidebar() {
  const { t } = useTranslation();
  const router = useRouter();
  const { session, newSession } = useAgentChat();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const hasLoaded = useRef(false);

  const refresh = useCallback(async () => {
    if (!hasLoaded.current) setLoadingSessions(true);
    try {
      setSessions(await listSessions(50, 0, { force: true }));
      hasLoaded.current = true;
    } catch (e) {
      console.error("Failed to load sessions", e);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, session.sessionId]);

  const handleNewChat = () => {
    newSession();
    router.push("/v2/chat");
  };

  const handleSelectSession = useCallback(
    (sessionId: string) => {
      router.push(`/v2/chat/${sessionId}`);
    },
    [router],
  );

  const handleRename = useCallback(
    async (sessionId: string, title: string) => {
      const updated = await updateSessionTitle(sessionId, title);
      setSessions((prev) =>
        prev.map((s) =>
          s.session_id === sessionId
            ? { ...s, title: updated.title, updated_at: updated.updated_at }
            : s,
        ),
      );
    },
    [],
  );

  const handleDelete = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Delete this chat history?"))) return;
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (session.sessionId === sessionId) {
        newSession();
        router.push("/v2/chat");
      }
    },
    [newSession, router, session.sessionId, t],
  );

  return (
    <SidebarShell
      showSessions
      sessions={sessions}
      activeSessionId={session.sessionId}
      loadingSessions={loadingSessions}
      onNewChat={handleNewChat}
      onSelectSession={handleSelectSession}
      onRenameSession={handleRename}
      onDeleteSession={handleDelete}
    />
  );
}
