"use client";

import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import * as api from "@/lib/tutorbot-api";
import type { TutorBotSummary, Soul } from "@/lib/tutorbot-api";
import { useAuth } from "@/context/AuthContext";

interface TutorBotState {
  bots: TutorBotSummary[];
  souls: Soul[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createAndStart: (payload: api.CreateBotPayload) => Promise<TutorBotSummary | null>;
  stopBot: (botId: string) => Promise<boolean>;
  destroyBot: (botId: string) => Promise<boolean>;
}

const TutorBotContext = createContext<TutorBotState | null>(null);

export function useTutorBots() {
  const ctx = useContext(TutorBotContext);
  if (!ctx) throw new Error("useTutorBots must be used within TutorBotProvider");
  return ctx;
}

export function TutorBotProvider({ children }: { children: React.ReactNode }) {
  const [bots, setBots] = useState<TutorBotSummary[]>([]);
  const [souls, setSouls] = useState<Soul[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const { isAuthenticated } = useAuth();

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [botList, soulList] = await Promise.all([
        api.listBots(),
        api.listSouls(),
      ]);
      if (mounted.current) {
        setBots(Array.isArray(botList) ? botList : []);
        setSouls(Array.isArray(soulList) ? soulList : []);
      }
    } catch (e) {
      if (mounted.current) {
        setError(e instanceof Error ? e.message : "Failed to load bots");
        setBots([]);
        setSouls([]);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (isAuthenticated) {
      refresh().finally(() => {
        if (mounted.current) setLoading(false);
      });
    } else {
      setLoading(false);
    }
    return () => { mounted.current = false; };
  }, [refresh, isAuthenticated]);

  const createAndStart = useCallback(async (payload: api.CreateBotPayload) => {
    try {
      setError(null);
      const bot = await api.createBot(payload);
      await refresh();
      return bot;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to create bot";
      if (mounted.current) setError(msg);
      return null;
    }
  }, [refresh]);

  const stop = useCallback(async (botId: string) => {
    try {
      await api.stopBot(botId);
      await refresh();
      return true;
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : "Failed to stop bot");
      return false;
    }
  }, [refresh]);

  const destroy = useCallback(async (botId: string) => {
    try {
      await api.destroyBot(botId);
      await refresh();
      return true;
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : "Failed to destroy bot");
      return false;
    }
  }, [refresh]);

  return (
    <TutorBotContext.Provider value={{ bots, souls, loading, error, refresh, createAndStart, stopBot: stop, destroyBot: destroy }}>
      {children}
    </TutorBotContext.Provider>
  );
}
