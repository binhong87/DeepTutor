"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ComposerActions } from "@/components/agent/ComposerActions";
import { AdvancedPanel } from "@/components/agent/AdvancedPanel";
import { useAgentChat } from "@/context/AgentChatContext";
import { listKnowledgeBases } from "@/lib/knowledge-api";
import type { KnowledgeBaseSummary } from "@/lib/knowledge-api";

// NOTE: ComposerInput (web/components/chat/home/ComposerInput.tsx) was
// intentionally NOT reused here. It manages its own internal text state,
// exposes { clear, getValue } (not { focus }), and requires ~12 props tied to
// the existing chat-space picker system (textareaRef, selectedCounts, six
// onSelect* callbacks, activeCapabilityKey, isMathAnimatorMode, etc.) that
// have no equivalent in the agent flow. A plain <textarea> with matching
// styles is the correct adaptation.

export function AgentComposer() {
  const { t } = useTranslation();
  const { session, sendMessage, cancelTurn, setKnowledgeBase, setHints } =
    useAgentChat();

  const [text, setText] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [kbs, setKbs] = useState<KnowledgeBaseSummary[]>([]);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    listKnowledgeBases().then(setKbs).catch(console.error);
  }, []);

  // Auto-resize the textarea as content changes (mirrors ComposerInput behaviour).
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "28px";
    const next = Math.max(el.scrollHeight, 28);
    const bounded = Math.min(next, 200);
    el.style.height = `${bounded}px`;
    el.style.overflowY = next > 200 ? "auto" : "hidden";
  }, [text]);

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || session.isStreaming) return;
    sendMessage({ content: trimmed });
    setText("");
    setAdvancedOpen(false);
    textareaRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="mx-auto w-full max-w-[760px] px-4 pb-6">
      <div className="flex flex-col gap-2">
        {advancedOpen && (
          <AdvancedPanel hints={session.hints} onHintsChange={setHints} />
        )}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 shadow-sm">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("Ask anything — I'll use the right tools")}
            disabled={session.isStreaming}
            rows={1}
            suppressHydrationWarning
            className="w-full resize-none overflow-hidden bg-transparent text-[15px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] disabled:opacity-60"
            style={{ transition: "height 0.15s ease-out", minHeight: 28 }}
          />
          <div className="mt-2">
            <ComposerActions
              knowledgeBases={kbs}
              activeKbId={session.knowledgeBaseId}
              llmSelection={session.llmSelection}
              hints={session.hints}
              advancedOpen={advancedOpen}
              isStreaming={session.isStreaming}
              onKbChange={setKnowledgeBase}
              onAdvancedToggle={() => setAdvancedOpen((v) => !v)}
              onSend={handleSend}
              onCancel={cancelTurn}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
