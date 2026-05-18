"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import { Bot, Loader2 } from "lucide-react";
import { Composer } from "./Composer";
import {
  connectBotWS,
  nextTurnId,
  type BotChatTurn,
  type LessonPlan,
} from "@/lib/bot-ws";
import { apiFetch, apiUrl } from "@/lib/api";
import AssistantResponse from "@/components/shared/AssistantResponse";
import LessonPlanCard from "@/components/tutorbot/chat/LessonPlanCard";
import { useSessionTree } from "@/context/SessionTreeContext";
import type { Attachment } from "../../../lib/agent-chat-types";
import { attachmentToWire } from "../../../lib/agent-chat-types";

interface BotInfo {
  bot_id: string;
  name: string;
  running: boolean;
}

export default function BotChatView({ botId, sessionId }: { botId: string; sessionId: string }) {
  const [bot, setBot] = useState<BotInfo | null>(null);
  const [turns, setTurns] = useState<BotChatTurn[]>([]);
  const [lessonPlan, setLessonPlan] = useState<LessonPlan | null>(null);
  const [connected, setConnected] = useState(false);
  const [sending, setSending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { patchPromotion, setActive, refresh: refreshTree } = useSessionTree();

  useEffect(() => {
    setActive(botId, sessionId);
    return () => setActive(null, null);
  }, [botId, sessionId, setActive]);

  // Surface the bot in the tree the first time a chat page is visited.
  useEffect(() => { void refreshTree(); }, [botId, refreshTree]);

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
    apiFetch(apiUrl(`/api/v1/tutorbot/${botId}/sessions/${sessionId}/history`))
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
  }, [botId, sessionId, scrollToBottom]);

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
    const ws = connectBotWS(botId, sessionId, updateTurn, ac.signal, {
      onLessonPlan: (plan) => setLessonPlan(plan),
      onSessionPromoted: (ev) => patchPromotion(botId, ev),
    });
    wsRef.current = ws;

    ws.addEventListener("open", () => setConnected(true));
    ws.addEventListener("close", () => setConnected(false));
    ws.addEventListener("error", () => setConnected(false));

    return () => {
      ac.abort();
      wsRef.current = null;
    };
  }, [botId, sessionId, updateTurn, patchPromotion]);

  useEffect(() => {
    scrollToBottom();
  }, [turns, scrollToBottom]);

  function handleSend(text: string, attachments: Attachment[] = []) {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const turnId = nextTurnId();
    const userTurn: BotChatTurn = {
      id: turnId,
      role: "user",
      content: text,
      thinking: [],
      status: "done",
      timestamp: Date.now(),
      attachments: attachments.length
        ? attachments.map((a) => ({
            type: a.type,
            filename: a.filename,
            mimeType: a.mimeType,
            base64: a.base64,
            previewUrl: a.previewUrl,
          }))
        : undefined,
    };
    setTurns((prev) => [...prev, userTurn]);
    setSending(true);
    scrollToBottom();

    const frame: Record<string, unknown> = { content: text };
    if (attachments.length > 0) {
      frame.attachments = attachments.map(attachmentToWire);
    }
    wsRef.current.send(JSON.stringify(frame));
  }

  // Detect when sending is done
  useEffect(() => {
    if (!sending) return;
    const last = turns[turns.length - 1];
    if (last && last.role === "bot" && (last.status === "done" || last.status === "error")) {
      setSending(false);
      // Refresh tree so the sidebar's `has_user_messages` flag (and any
      // server-side mutations the bot made) catch up — e.g. M3 "+ New chat"
      // becomes enabled after the first user message lands.
      void refreshTree();
    }
  }, [turns, sending, refreshTree]);

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
                <div className="flex max-w-[80%] flex-col items-end gap-2">
                  {turn.attachments && turn.attachments.length > 0 && (
                    <div className="flex flex-wrap justify-end gap-2">
                      {turn.attachments.map((att, i) => {
                        if (att.type === "image") {
                          const src =
                            att.previewUrl ??
                            (att.base64
                              ? `data:${att.mimeType};base64,${att.base64}`
                              : undefined);
                          return src ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              key={i}
                              src={src}
                              alt={att.filename}
                              className="max-h-48 max-w-full rounded-lg border border-[var(--border)] object-contain"
                            />
                          ) : (
                            <span key={i} className="text-xs text-[var(--muted-foreground)]">
                              {att.filename}
                            </span>
                          );
                        }
                        if (att.type === "audio") {
                          const src = att.base64
                            ? `data:${att.mimeType};base64,${att.base64}`
                            : undefined;
                          return src ? (
                            // eslint-disable-next-line jsx-a11y/media-has-caption
                            <audio key={i} src={src} controls className="max-w-full" />
                          ) : (
                            <span key={i} className="text-xs text-[var(--muted-foreground)]">
                              🎤 {att.filename}
                            </span>
                          );
                        }
                        return null;
                      })}
                    </div>
                  )}
                  {turn.content && (
                    <div className="rounded-2xl rounded-br-md bg-[var(--primary)] px-4 py-2.5 text-[14px] text-[var(--primary-foreground)] whitespace-pre-wrap">
                      {turn.content}
                    </div>
                  )}
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
      <Composer
        onSend={handleSend}
        disabled={!connected}
        sending={sending}
        placeholder={connected ? "Type a message..." : "Connecting..."}
      />
    </div>
  );
}
