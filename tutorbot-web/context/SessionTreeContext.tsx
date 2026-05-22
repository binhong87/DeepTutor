"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getTutorbotTree, type BotTreeRow, type SessionRow } from "@/lib/tutorbot-api";
import type { SessionPromotedEvent } from "@/lib/bot-ws";

interface SessionTreeState {
  tree: BotTreeRow[];
  expanded: Record<string, boolean>;
  activeBotId: string | null;
  activeSessionId: string | null;
  refresh: () => Promise<void>;
  toggleBot: (botId: string) => void;
  setActive: (botId: string | null, sessionId: string | null) => void;
  patchPromotion: (botId: string, ev: SessionPromotedEvent) => void;
}

const EXPAND_KEY = "deeptutor.sidebar.expanded";

function loadExpanded(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem(EXPAND_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveExpanded(map: Record<string, boolean>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(EXPAND_KEY, JSON.stringify(map));
  } catch {
    /* ignore quota errors */
  }
}

const Context = createContext<SessionTreeState | null>(null);

export function SessionTreeProvider({ children }: { children: React.ReactNode }) {
  const [tree, setTree] = useState<BotTreeRow[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => loadExpanded());
  const [activeBotId, setActiveBotId] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const rows = await getTutorbotTree();
      setTree(rows);
    } catch (e) {
      console.warn("Failed to load tutorbot tree", e);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggleBot = useCallback((botId: string) => {
    setExpanded((prev) => {
      const next = { ...prev, [botId]: !prev[botId] };
      saveExpanded(next);
      return next;
    });
  }, []);

  const setActive = useCallback((botId: string | null, sessionId: string | null) => {
    setActiveBotId(botId);
    setActiveSessionId(sessionId);
    if (botId) {
      setExpanded((prev) => {
        if (prev[botId]) return prev;
        const next = { ...prev, [botId]: true };
        saveExpanded(next);
        return next;
      });
    }
  }, []);

  const patchPromotion = useCallback((botId: string, ev: SessionPromotedEvent) => {
    setTree((prev) =>
      prev.map((b) => {
        if (b.bot_id !== botId) return b;

        const alreadyExists = b.sessions.some((s) => s.id === ev.promoted.id);
        let sessions: SessionRow[];

        if (alreadyExists) {
          // Default → active promotion: update the existing session in place.
          sessions = b.sessions.map((s) =>
            s.id === ev.promoted.id
              ? {
                  ...s,
                  title: ev.promoted.title,
                  title_source: ev.promoted.title_source,
                  status: "active",
                  lesson_plan_brief: ev.promoted.lesson_plan_brief,
                }
              : s,
          );
        } else {
          // Fork: brand-new session → insert it at the top of the list.
          sessions = [
            {
              id: ev.promoted.id,
              title: ev.promoted.title,
              title_source: ev.promoted.title_source,
              status: "active",
              updated_at: new Date().toISOString(),
              has_user_messages: false,
              lesson_plan_brief: ev.promoted.lesson_plan_brief,
            },
            ...b.sessions,
          ];
        }

        if (ev.new_default.id && !sessions.some((s) => s.id === ev.new_default.id)) {
          sessions.unshift({
            id: ev.new_default.id,
            title: "",
            title_source: null,
            status: "default",
            updated_at: new Date().toISOString(),
            has_user_messages: false,
            lesson_plan_brief: null,
          });
        }
        return { ...b, sessions };
      }),
    );
  }, []);

  const value = useMemo<SessionTreeState>(
    () => ({
      tree,
      expanded,
      activeBotId,
      activeSessionId,
      refresh,
      toggleBot,
      setActive,
      patchPromotion,
    }),
    [tree, expanded, activeBotId, activeSessionId, refresh, toggleBot, setActive, patchPromotion],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSessionTree(): SessionTreeState {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useSessionTree must be used inside SessionTreeProvider");
  return ctx;
}
