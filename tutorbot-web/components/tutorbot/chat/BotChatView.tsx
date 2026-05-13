"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import { Bot, Loader2, Send } from "lucide-react";
import {
  connectBotWS,
  nextTurnId,
  type BotChatTurn,
  type LessonPlan,
} from "@/lib/bot-ws";
import { apiFetch, apiUrl } from "@/lib/api";
import AssistantResponse from "@/components/shared/AssistantResponse";
import LessonPlanCard from "@/components/tutorbot/chat/LessonPlanCard";

interface BotInfo {
  bot_id: string;
  name: string;
  running: boolean;
}

export default function BotChatView({ botId }: { botId: string }) {
  const [bot, setBot] = useState<BotInfo | null>(null);
  const [turns, setTurns] = useState<BotChatTurn[]>([]);
  const [lessonPlan, setLessonPlan] = useState<LessonPlan | null>(null);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [sending, setSending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior,
      });
    });
  }, []);

  // Load bot info
  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl(`/api/v1/tutorbot/${botId}`))
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (!cancelled) setBot(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [botId]);

  // Load history
  useEffect(() => {
    let cancelled = false;
    setLoadingHistory(true);
    apiFetch(apiUrl(`/api/v1/tutorbot/${botId}/history`))
      .then((r) => (r.ok ? r.json() : []))
      .then((history: { role: string; content: string }[]) => {
        if (cancelled) return;
        const restored: BotChatTurn[] = history
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m, i) => ({
            id: `history-${i}`,
            role: m.role === "assistant" ? "bot" : "user",
            content: m.content,
            thinking: [],
            status: "done" as const,
            timestamp: Date.now() - (history.length - i) * 1000,
          }));
        setTurns(restored);
        setLoadingHistory(false);
        if (restored.length) {
          setTimeout(() => scrollToBottom("instant"), 100);
        }
      })
      .catch(() => { if (!cancelled) setLoadingHistory(false); });
    return () => { cancelled = true; };
  }, [botId, scrollToBottom]);

  const updateTurn = useCallback((turnId: string, updater: (turn: BotChatTurn) => BotChatTurn) => {
    setTurns((prev) => {
      const idx = prev.findIndex((t) => t.id === turnId);
      if (idx === -1) {
        const base: BotChatTurn = {
          id: turnId,
          role: "bot",
          content: "",
          thinking: [],
          status: "thinking",
          timestamp: Date.now(),
        };
        return [...prev, updater(base)];
      }
      const updated = prev.slice();
      updated[idx] = updater(updated[idx]);
      return updated;
    });
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    const ws = connectBotWS(botId, updateTurn, ac.signal, (plan) => {
      setLessonPlan(plan);
    });
    wsRef.current = ws;

    ws.addEventListener("open", () => setConnected(true));
    ws.addEventListener("close", () => setConnected(false));
    ws.addEventListener("error", () => setConnected(false));

    return () => {
      ac.abort();
      wsRef.current = null;
    };
  }, [botId, updateTurn]);

  useEffect(() => {
    scrollToBottom();
  }, [turns, scrollToBottom]);

  function handleSend() {
    const text = input.trim();
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const turnId = nextTurnId();
    const userTurn: BotChatTurn = {
      id: turnId,
      role: "user",
      content: text,
      thinking: [],
      status: "done",
      timestamp: Date.now(),
    };
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    setSending(true);
    scrollToBottom();

    wsRef.current.send(JSON.stringify({ content: text }));
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // Detect when sending is done
  useEffect(() => {
    if (!sending) return;
    const last = turns[turns.length - 1];
    if (last && last.role === "bot" && (last.status === "done" || last.status === "error")) {
      setSending(false);
    }
  }, [turns, sending]);

  const showEmpty = turns.length === 0 && !sending && !loadingHistory;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[var(--border)] px-5 py-3 shrink-0">
        <Bot className="h-4 w-4 text-[var(--muted-foreground)]" />
        <span className="text-[14px] font-medium text-[var(--foreground)]">
          {bot?.name ?? botId}
        </span>
        {bot?.running && (
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
        )}
        {connected && !bot?.running && (
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
        )}
        {!connected && (
          <span className="h-2 w-2 rounded-full bg-yellow-500" />
        )}
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-5 py-6 [scrollbar-gutter:stable]"
      >
        <div className="mx-auto max-w-[720px] space-y-5">
          {lessonPlan && lessonPlan.steps.length > 0 && (
            <LessonPlanCard plan={lessonPlan} />
          )}

          {loadingHistory && (
            <div className="flex items-center justify-center pt-24">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
            </div>
          )}

          {showEmpty && (
            <div className="flex flex-col items-center justify-center pt-24 text-center">
              <div className="mb-3 rounded-xl bg-[var(--muted)] p-3 text-[var(--muted-foreground)]">
                <Bot size={22} />
              </div>
              <p className="text-[14px] font-medium text-[var(--foreground)]">
                Chat with {bot?.name ?? botId}
              </p>
              <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                Send a message to start the conversation.
              </p>
            </div>
          )}

          {turns.map((turn) => (
            <div
              key={turn.id}
              className={turn.role === "user" ? "flex justify-end" : ""}
            >
              {turn.role === "user" ? (
                <div className="max-w-[80%] rounded-2xl rounded-br-md bg-[var(--primary)] px-4 py-2.5 text-[14px] text-[var(--primary-foreground)] whitespace-pre-wrap">
                  {turn.content}
                </div>
              ) : (
                <div className="max-w-full">
                  {turn.thinking.length > 0 && (
                    <details className="mb-2" open={turn.status === "thinking"}>
                      <summary className="cursor-pointer text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
                        Thinking ({turn.thinking.length} step{turn.thinking.length !== 1 ? "s" : ""})
                      </summary>
                      <div className="mt-1 space-y-1 border-l-2 border-[var(--border)] pl-3">
                        {turn.thinking.map((th, j) => (
                          <p key={j} className="text-[12px] text-[var(--muted-foreground)]">
                            {th}
                          </p>
                        ))}
                      </div>
                    </details>
                  )}
                  {turn.content && (
                    <AssistantResponse content={turn.content} />
                  )}
                  {turn.status === "error" && !turn.content && (
                    <p className="text-[13px] text-red-500">
                      An error occurred while generating the response.
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}

          {/* Streaming indicator */}
          {sending && turns[turns.length - 1]?.role === "user" && (
            <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Thinking...</span>
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border)] px-5 py-3 shrink-0">
        <div className="mx-auto flex max-w-[720px] items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-[14px] leading-[1.5] placeholder:text-[var(--muted-foreground)]/60 focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            placeholder={connected ? "Type a message..." : "Connecting..."}
            disabled={!connected || sending}
          />
          <button
            onClick={handleSend}
            disabled={!connected || !input.trim() || sending}
            className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
