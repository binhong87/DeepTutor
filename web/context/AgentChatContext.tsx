"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { UnifiedWSClient, type StreamEvent } from "@/lib/unified-ws";
import {
  agentChatReducer,
  makeInitialSession,
  type AgentAction,
  type AgentAttachment,
  type AgentLLMSelection,
  type AgentSession,
  type AgentTurn,
  type RichOutputType,
  type SourceRef,
  type StepEvent,
  type StepEventKind,
} from "@/lib/agent-chat-types";

const ALL_TOOLS = [
  "brainstorm",
  "rag",
  "web_search",
  "code_execution",
  "reason",
  "paper_search",
] as const;

const LS_KB_KEY = "deeptutor-v2-kb";
const LS_LLM_KEY = "deeptutor-v2-llm";

interface AgentChatContextValue {
  session: AgentSession;
  sendMessage: (params: {
    content: string;
    attachments?: AgentAttachment[];
  }) => void;
  cancelTurn: () => void;
  setKnowledgeBase: (id: string | null) => void;
  setLLMSelection: (sel: AgentLLMSelection | null) => void;
  setHints: (hints: string[]) => void;
  loadSession: (sessionId: string) => Promise<void>;
  newSession: () => void;
}

const AgentChatContext = createContext<AgentChatContextValue | null>(null);

function mapStreamEvent(
  event: StreamEvent,
  activeTurnId: string | null,
): AgentAction | null {
  switch (event.type) {
    case "session":
      return {
        type: "BIND_SESSION",
        sessionId: event.session_id ?? "",
        richOutputType:
          (event.metadata?.capability as RichOutputType) ?? undefined,
      };

    case "stage_start":
    case "stage_end":
    case "thinking":
    case "tool_call":
    case "tool_result":
    case "observation": {
      const step: StepEvent = {
        id: event.turn_id
          ? `${event.turn_id}-${event.stage}-${event.type}`
          : `step-${Date.now()}`,
        type: event.type as StepEventKind,
        label: event.content || event.stage || event.type,
        detail: event.metadata
          ? JSON.stringify(event.metadata)
          : undefined,
        done:
          event.type === "stage_end" || event.type === "tool_result",
        timestamp: event.timestamp,
      };
      return { type: "STREAM_STEP", step };
    }

    case "content":
      if (!activeTurnId) return null;
      return {
        type: "STREAM_CONTENT",
        turnId: activeTurnId,
        delta: event.content,
      };

    case "sources": {
      if (!activeTurnId) return null;
      const sources = (event.metadata?.sources ?? []) as SourceRef[];
      return { type: "STREAM_SOURCES", turnId: activeTurnId, sources };
    }

    case "result": {
      if (!activeTurnId) return null;
      const capability = event.metadata?.capability as RichOutputType;
      if (!capability) return null;
      return {
        type: "STREAM_RICH_OUTPUT",
        turnId: activeTurnId,
        richOutputType: capability,
        data: event.metadata,
      };
    }

    case "done":
      if (!activeTurnId) return null;
      return { type: "STREAM_DONE", turnId: activeTurnId };

    case "error":
      if (!activeTurnId) return null;
      return {
        type: "STREAM_ERROR",
        turnId: activeTurnId,
        message: event.content || "Unknown error",
      };

    default:
      return null;
  }
}

export function AgentChatProvider({ children }: { children: ReactNode }) {
  const [session, dispatch] = useReducer(agentChatReducer, undefined, () => {
    const initial = makeInitialSession();
    if (typeof window !== "undefined") {
      const kb = localStorage.getItem(LS_KB_KEY);
      const llm = localStorage.getItem(LS_LLM_KEY);
      return {
        ...initial,
        knowledgeBaseId: kb,
        llmSelection: llm ? (JSON.parse(llm) as AgentLLMSelection) : null,
      };
    }
    return initial;
  });

  const wsRef = useRef<UnifiedWSClient | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);

  useEffect(() => {
    const lastTurn = session.turns[session.turns.length - 1];
    if (lastTurn?.status === "streaming") {
      activeTurnIdRef.current = lastTurn.id;
    }
  }, [session.turns]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (session.knowledgeBaseId) {
      localStorage.setItem(LS_KB_KEY, session.knowledgeBaseId);
    } else {
      localStorage.removeItem(LS_KB_KEY);
    }
  }, [session.knowledgeBaseId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (session.llmSelection) {
      localStorage.setItem(
        LS_LLM_KEY,
        JSON.stringify(session.llmSelection),
      );
    } else {
      localStorage.removeItem(LS_LLM_KEY);
    }
  }, [session.llmSelection]);

  const getOrCreateWS = useCallback((): UnifiedWSClient => {
    if (!wsRef.current) {
      wsRef.current = new UnifiedWSClient(
        (event: StreamEvent) => {
          const action = mapStreamEvent(event, activeTurnIdRef.current);
          if (action) dispatch(action);
        },
        () => {
          const turnId = activeTurnIdRef.current;
          if (turnId) {
            dispatch({
              type: "STREAM_ERROR",
              turnId,
              message: "Connection lost",
            });
          }
        },
      );
    }
    wsRef.current.connect();
    return wsRef.current;
  }, []);

  const sendMessage = useCallback(
    ({
      content,
      attachments = [],
    }: {
      content: string;
      attachments?: AgentAttachment[];
    }) => {
      const turnId = `turn-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      activeTurnIdRef.current = turnId;
      const newTurn: AgentTurn = {
        id: turnId,
        userContent: content,
        userAttachments: attachments,
        assistantContent: "",
        steps: [],
        richOutputType: null,
        richOutputData: null,
        sources: [],
        status: "streaming",
      };
      dispatch({ type: "NEW_TURN", turn: newTurn });
      const ws = getOrCreateWS();
      ws.setResumeState(turnId, 0);
      ws.send({
        type: "start_turn",
        content,
        tools: [...ALL_TOOLS],
        capability: "",
        knowledge_bases: session.knowledgeBaseId
          ? [session.knowledgeBaseId]
          : [],
        session_id: session.sessionId,
        llm_selection: session.llmSelection,
        config: session.hints.length
          ? { hints: session.hints }
          : undefined,
        attachments: attachments.map((a) => ({
          type: a.type,
          url: a.url,
          filename: a.name,
        })),
      });
    },
    [
      getOrCreateWS,
      session.sessionId,
      session.knowledgeBaseId,
      session.llmSelection,
      session.hints,
    ],
  );

  const cancelTurn = useCallback(() => {
    const turnId = activeTurnIdRef.current;
    if (!turnId || !wsRef.current) return;
    wsRef.current.send({ type: "cancel_turn", turn_id: turnId });
  }, []);

  const setKnowledgeBase = useCallback(
    (id: string | null) =>
      dispatch({ type: "SET_KB", knowledgeBaseId: id }),
    [],
  );

  const setLLMSelection = useCallback(
    (sel: AgentLLMSelection | null) =>
      dispatch({ type: "SET_LLM", llmSelection: sel }),
    [],
  );

  const setHints = useCallback(
    (hints: string[]) => dispatch({ type: "SET_HINTS", hints }),
    [],
  );

  const loadSession = useCallback(async (sessionId: string) => {
    const { getSession } = await import("@/lib/session-api");
    const data = await getSession(sessionId);

    // SessionDetail returns flat messages[] with role-based entries.
    // Reconstruct AgentTurn objects by pairing consecutive user → assistant messages.
    const msgs = data.messages ?? [];
    const turns: AgentTurn[] = [];

    for (let i = 0; i < msgs.length; i++) {
      const msg = msgs[i];
      if (msg.role !== "user") continue;

      const nextMsg = msgs[i + 1];
      const assistantContent =
        nextMsg?.role === "assistant" ? nextMsg.content : "";

      turns.push({
        id: String(msg.id),
        userContent: msg.content,
        userAttachments: (msg.attachments ?? []).map((a) => ({
          name: a.filename ?? "",
          url: a.url ?? "",
          type: a.type,
        })),
        assistantContent,
        steps: [],
        richOutputType: null,
        richOutputData: null,
        sources: [],
        status: "done" as const,
      });

      // Skip the paired assistant message so it is not processed as a user turn.
      if (nextMsg?.role === "assistant") i++;
    }

    dispatch({
      type: "LOAD_SESSION",
      turns,
      sessionId: data.session_id || data.id,
    });
  }, []);

  const newSession = useCallback(() => {
    wsRef.current?.disconnect();
    wsRef.current = null;
    activeTurnIdRef.current = null;
    dispatch({ type: "LOAD_SESSION", turns: [], sessionId: null });
    dispatch({ type: "SET_KB", knowledgeBaseId: session.knowledgeBaseId });
    dispatch({ type: "SET_LLM", llmSelection: session.llmSelection });
  }, [session.knowledgeBaseId, session.llmSelection]);

  return (
    <AgentChatContext.Provider
      value={{
        session,
        sendMessage,
        cancelTurn,
        setKnowledgeBase,
        setLLMSelection,
        setHints,
        loadSession,
        newSession,
      }}
    >
      {children}
    </AgentChatContext.Provider>
  );
}

export function useAgentChat(): AgentChatContextValue {
  const ctx = useContext(AgentChatContext);
  if (!ctx) {
    throw new Error("useAgentChat must be used within AgentChatProvider");
  }
  return ctx;
}
