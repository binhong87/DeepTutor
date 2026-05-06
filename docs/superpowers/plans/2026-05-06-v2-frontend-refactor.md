# V2 Frontend — Agent Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/v2/chat` route with a unified agent chat UI where the LLM automatically selects tools, live step streaming renders inside the response bubble, and a minimal composer with optional tool-hint panel is provided.

**Architecture:** New `(v2)` route group alongside existing `(workspace)`. Pure types + reducer live in `web/lib/agent-chat-types.ts` (no React — node-testable). `AgentChatContext` wires the reducer to `UnifiedWSClient`. Eleven new components in `web/components/agent/`. Two existing files modified (sidebar nav href + root redirect). All existing features untouched.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, framer-motion, i18next, existing `UnifiedWSClient` (`web/lib/unified-ws.ts`), Node `node:test` for reducer unit tests.

---

## File Map

| File | Status | Purpose |
|---|---|---|
| `web/lib/agent-chat-types.ts` | Create | Types + pure reducer (no React) |
| `web/tests/agent-chat-reducer.test.ts` | Create | Reducer unit tests |
| `web/context/AgentChatContext.tsx` | Create | React context + WS orchestration |
| `web/components/agent/AdvancedPanel.tsx` | Create | Collapsible tool-hint checkboxes |
| `web/components/agent/ComposerActions.tsx` | Create | KB selector + Advanced pill + Send/Cancel |
| `web/components/agent/AgentComposer.tsx` | Create | Full composer bar |
| `web/components/agent/UserMessage.tsx` | Create | User bubble |
| `web/components/agent/AgentStepTimeline.tsx` | Create | Live step stream + collapsed summary |
| `web/components/agent/AgentMessage.tsx` | Create | Assistant turn container |
| `web/components/agent/RichOutputEmbed.tsx` | Create | Lazy-load shell for rich viewers |
| `web/components/agent/MessageFeed.tsx` | Create | Scrollable turn list |
| `web/components/agent/V2Sidebar.tsx` | Create | Sidebar wired to AgentChatContext |
| `web/app/(v2)/layout.tsx` | Create | Route group layout |
| `web/app/(v2)/chat/[[...sessionId]]/page.tsx` | Create | AgentChatPage |
| `web/components/sidebar/SidebarShell.tsx` | Modify | Chat href `/chat` → `/v2/chat` |
| `web/app/(workspace)/page.tsx` | Modify | Root redirect `/chat` → `/v2/chat` |
| `web/locales/en/app.json` | Modify | Add i18n keys |
| `web/locales/zh/app.json` | Modify | Add i18n keys (Chinese) |

---

## Task 1: Types and reducer

**Files:**
- Create: `web/lib/agent-chat-types.ts`
- Create: `web/tests/agent-chat-reducer.test.ts`

- [ ] **Step 1: Write the failing test**

Create `web/tests/agent-chat-reducer.test.ts`:

```typescript
import test from "node:test";
import assert from "node:assert/strict";

import {
  agentChatReducer,
  makeInitialSession,
} from "../lib/agent-chat-types";

test("NEW_TURN: adds a turn and sets streaming state", () => {
  const state = makeInitialSession();
  const turn = {
    id: "t1", userContent: "hello", userAttachments: [],
    assistantContent: "", steps: [], richOutputType: null as null,
    richOutputData: null, sources: [], status: "streaming" as const,
  };
  const next = agentChatReducer(state, { type: "NEW_TURN", turn });
  assert.equal(next.turns.length, 1);
  assert.equal(next.isStreaming, true);
  assert.equal(next.status, "streaming");
  assert.deepEqual(next.activeSteps, []);
});

test("STREAM_CONTENT: appends delta to the matching turn", () => {
  const state = makeInitialSession();
  const turn = {
    id: "t1", userContent: "q", userAttachments: [], assistantContent: "",
    steps: [], richOutputType: null as null, richOutputData: null,
    sources: [], status: "streaming" as const,
  };
  let s = agentChatReducer(state, { type: "NEW_TURN", turn });
  s = agentChatReducer(s, { type: "STREAM_CONTENT", turnId: "t1", delta: "Hello" });
  s = agentChatReducer(s, { type: "STREAM_CONTENT", turnId: "t1", delta: " world" });
  assert.equal(s.turns[0].assistantContent, "Hello world");
});

test("STREAM_STEP: adds a new step to activeSteps", () => {
  const state = makeInitialSession();
  const step = {
    id: "s1", type: "thinking" as const,
    label: "Reasoning…", done: false, timestamp: 1000,
  };
  const next = agentChatReducer(state, { type: "STREAM_STEP", step });
  assert.equal(next.activeSteps.length, 1);
  assert.equal(next.activeSteps[0].id, "s1");
});

test("STREAM_STEP: updates an existing step in-place", () => {
  let state = makeInitialSession();
  const step = {
    id: "s1", type: "thinking" as const,
    label: "Reasoning…", done: false, timestamp: 1000,
  };
  state = agentChatReducer(state, { type: "STREAM_STEP", step });
  state = agentChatReducer(state, {
    type: "STREAM_STEP", step: { ...step, done: true, label: "Reasoned" },
  });
  assert.equal(state.activeSteps.length, 1);
  assert.equal(state.activeSteps[0].done, true);
  assert.equal(state.activeSteps[0].label, "Reasoned");
});

test("STREAM_DONE: finalises turn, moves activeSteps into turn, clears streaming", () => {
  let state = makeInitialSession();
  const turn = {
    id: "t1", userContent: "q", userAttachments: [], assistantContent: "ans",
    steps: [], richOutputType: null as null, richOutputData: null,
    sources: [], status: "streaming" as const,
  };
  state = agentChatReducer(state, { type: "NEW_TURN", turn });
  state = agentChatReducer(state, {
    type: "STREAM_STEP",
    step: { id: "s1", type: "thinking" as const, label: "…", done: true, timestamp: 1 },
  });
  state = agentChatReducer(state, { type: "STREAM_DONE", turnId: "t1" });
  assert.equal(state.isStreaming, false);
  assert.equal(state.status, "idle");
  assert.deepEqual(state.activeSteps, []);
  assert.equal(state.turns[0].status, "done");
  assert.equal(state.turns[0].steps.length, 1);
});

test("SET_KB: updates knowledgeBaseId", () => {
  const state = makeInitialSession();
  const next = agentChatReducer(state, { type: "SET_KB", knowledgeBaseId: "kb-1" });
  assert.equal(next.knowledgeBaseId, "kb-1");
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd web && npm run test:node
```

Expected: compile error — `../lib/agent-chat-types` does not exist.

- [ ] **Step 3: Create `web/lib/agent-chat-types.ts`**

```typescript
// Pure types and reducer — no React imports, safe to use in node:test.

export type StepEventKind =
  | "stage_start"
  | "stage_end"
  | "thinking"
  | "tool_call"
  | "tool_result"
  | "observation";

export interface StepEvent {
  id: string;
  type: StepEventKind;
  label: string;
  detail?: string;
  done: boolean;
  timestamp: number;
}

export interface SourceRef {
  title: string;
  url?: string;
  snippet?: string;
}

export interface AgentAttachment {
  name: string;
  url: string;
  type: string;
}

export interface AgentLLMSelection {
  profile_id: string;
  model_id: string;
}

export type RichOutputType =
  | "quiz"
  | "math_animator"
  | "visualize"
  | "deep_research"
  | null;

export interface AgentTurn {
  id: string;
  userContent: string;
  userAttachments: AgentAttachment[];
  assistantContent: string;
  steps: StepEvent[];
  richOutputType: RichOutputType;
  richOutputData: unknown;
  sources: SourceRef[];
  status: "streaming" | "done" | "error";
  errorMessage?: string;
}

export interface AgentSession {
  sessionId: string | null;
  turns: AgentTurn[];
  activeSteps: StepEvent[];
  knowledgeBaseId: string | null;
  llmSelection: AgentLLMSelection | null;
  hints: string[];
  isStreaming: boolean;
  status: "idle" | "streaming" | "error";
}

export function makeInitialSession(): AgentSession {
  return {
    sessionId: null,
    turns: [],
    activeSteps: [],
    knowledgeBaseId: null,
    llmSelection: null,
    hints: [],
    isStreaming: false,
    status: "idle",
  };
}

// ── Reducer ────────────────────────────────────────────────────────────────

export type AgentAction =
  | { type: "NEW_TURN"; turn: AgentTurn }
  | { type: "STREAM_STEP"; step: StepEvent }
  | { type: "STREAM_CONTENT"; turnId: string; delta: string }
  | { type: "STREAM_RICH_OUTPUT"; turnId: string; richOutputType: RichOutputType; data: unknown }
  | { type: "STREAM_SOURCES"; turnId: string; sources: SourceRef[] }
  | { type: "STREAM_DONE"; turnId: string }
  | { type: "STREAM_ERROR"; turnId: string; message: string }
  | { type: "BIND_SESSION"; sessionId: string; richOutputType?: RichOutputType }
  | { type: "LOAD_SESSION"; turns: AgentTurn[]; sessionId: string | null }
  | { type: "SET_KB"; knowledgeBaseId: string | null }
  | { type: "SET_LLM"; llmSelection: AgentLLMSelection | null }
  | { type: "SET_HINTS"; hints: string[] };

export function agentChatReducer(
  state: AgentSession,
  action: AgentAction,
): AgentSession {
  switch (action.type) {
    case "NEW_TURN":
      return {
        ...state,
        turns: [...state.turns, action.turn],
        activeSteps: [],
        isStreaming: true,
        status: "streaming",
      };

    case "STREAM_STEP": {
      const idx = state.activeSteps.findIndex((s) => s.id === action.step.id);
      const activeSteps =
        idx >= 0
          ? state.activeSteps.map((s, i) => (i === idx ? { ...s, ...action.step } : s))
          : [...state.activeSteps, action.step];
      return { ...state, activeSteps };
    }

    case "STREAM_CONTENT":
      return {
        ...state,
        turns: state.turns.map((t) =>
          t.id === action.turnId
            ? { ...t, assistantContent: t.assistantContent + action.delta }
            : t,
        ),
      };

    case "STREAM_RICH_OUTPUT":
      return {
        ...state,
        turns: state.turns.map((t) =>
          t.id === action.turnId
            ? { ...t, richOutputType: action.richOutputType, richOutputData: action.data }
            : t,
        ),
      };

    case "STREAM_SOURCES":
      return {
        ...state,
        turns: state.turns.map((t) =>
          t.id === action.turnId ? { ...t, sources: action.sources } : t,
        ),
      };

    case "STREAM_DONE":
      return {
        ...state,
        isStreaming: false,
        status: "idle",
        activeSteps: [],
        turns: state.turns.map((t) =>
          t.id === action.turnId
            ? { ...t, status: "done", steps: state.activeSteps }
            : t,
        ),
      };

    case "STREAM_ERROR":
      return {
        ...state,
        isStreaming: false,
        status: "error",
        activeSteps: [],
        turns: state.turns.map((t) =>
          t.id === action.turnId
            ? { ...t, status: "error", errorMessage: action.message, steps: state.activeSteps }
            : t,
        ),
      };

    case "BIND_SESSION":
      return {
        ...state,
        sessionId: action.sessionId,
        ...(action.richOutputType
          ? {
              turns: state.turns.map((t, i) =>
                i === state.turns.length - 1
                  ? { ...t, richOutputType: action.richOutputType! }
                  : t,
              ),
            }
          : {}),
      };

    case "LOAD_SESSION":
      return {
        ...state,
        sessionId: action.sessionId,
        turns: action.turns,
        activeSteps: [],
        isStreaming: false,
        status: "idle",
      };

    case "SET_KB":
      return { ...state, knowledgeBaseId: action.knowledgeBaseId };

    case "SET_LLM":
      return { ...state, llmSelection: action.llmSelection };

    case "SET_HINTS":
      return { ...state, hints: action.hints };

    default:
      return state;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

```
cd web && npm run test:node
```

Expected: all 6 tests pass with output like `# pass 6`.

- [ ] **Step 5: Commit**

```bash
git add web/lib/agent-chat-types.ts web/tests/agent-chat-reducer.test.ts
git commit -m "feat(v2): add agent chat types and reducer with tests"
```

---

## Task 2: AgentChatContext

**Files:**
- Create: `web/context/AgentChatContext.tsx`

- [ ] **Step 1: Create `web/context/AgentChatContext.tsx`**

```tsx
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
  "brainstorm", "rag", "web_search", "code_execution", "reason", "paper_search",
] as const;

const LS_KB_KEY = "deeptutor-v2-kb";
const LS_LLM_KEY = "deeptutor-v2-llm";

interface AgentChatContextValue {
  session: AgentSession;
  sendMessage: (params: { content: string; attachments?: AgentAttachment[] }) => void;
  cancelTurn: () => void;
  setKnowledgeBase: (id: string | null) => void;
  setLLMSelection: (sel: AgentLLMSelection | null) => void;
  setHints: (hints: string[]) => void;
  loadSession: (sessionId: string) => Promise<void>;
  newSession: () => void;
}

const AgentChatContext = createContext<AgentChatContextValue | null>(null);

function mapStreamEvent(event: StreamEvent, activeTurnId: string | null): AgentAction | null {
  switch (event.type) {
    case "session":
      return {
        type: "BIND_SESSION",
        sessionId: event.session_id ?? "",
        richOutputType: (event.metadata?.capability as RichOutputType) ?? undefined,
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
        detail: event.metadata ? JSON.stringify(event.metadata) : undefined,
        done: event.type === "stage_end" || event.type === "tool_result",
        timestamp: event.timestamp,
      };
      return { type: "STREAM_STEP", step };
    }

    case "content":
      if (!activeTurnId) return null;
      return { type: "STREAM_CONTENT", turnId: activeTurnId, delta: event.content ?? "" };

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
      return { type: "STREAM_ERROR", turnId: activeTurnId, message: event.content ?? "Unknown error" };

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
    if (lastTurn?.status === "streaming") activeTurnIdRef.current = lastTurn.id;
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
      localStorage.setItem(LS_LLM_KEY, JSON.stringify(session.llmSelection));
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
          if (turnId) dispatch({ type: "STREAM_ERROR", turnId, message: "Connection lost" });
        },
      );
    }
    wsRef.current.connect();
    return wsRef.current;
  }, []);

  const sendMessage = useCallback(
    ({ content, attachments = [] }: { content: string; attachments?: AgentAttachment[] }) => {
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
        knowledge_bases: session.knowledgeBaseId ? [session.knowledgeBaseId] : [],
        session_id: session.sessionId,
        llm_selection: session.llmSelection,
        config: session.hints.length ? { hints: session.hints } : undefined,
        attachments: attachments.map((a) => ({ type: a.type, url: a.url, filename: a.name })),
      });
    },
    [getOrCreateWS, session.sessionId, session.knowledgeBaseId, session.llmSelection, session.hints],
  );

  const cancelTurn = useCallback(() => {
    const turnId = activeTurnIdRef.current;
    if (!turnId || !wsRef.current) return;
    wsRef.current.send({ type: "cancel_turn", turn_id: turnId });
  }, []);

  const setKnowledgeBase = useCallback(
    (id: string | null) => dispatch({ type: "SET_KB", knowledgeBaseId: id }),
    [],
  );

  const setLLMSelection = useCallback(
    (sel: AgentLLMSelection | null) => dispatch({ type: "SET_LLM", llmSelection: sel }),
    [],
  );

  const setHints = useCallback(
    (hints: string[]) => dispatch({ type: "SET_HINTS", hints }),
    [],
  );

  const loadSession = useCallback(async (sessionId: string) => {
    const { getSession } = await import("@/lib/session-api");
    const data = await getSession(sessionId);
    const turns: AgentTurn[] = (data.turns ?? []).map((t: Record<string, unknown>) => ({
      id: (t.turn_id as string) ?? `turn-${Date.now()}`,
      userContent: (t.user_content as string) ?? "",
      userAttachments: [],
      assistantContent: (t.assistant_content as string) ?? "",
      steps: [],
      richOutputType: null,
      richOutputData: null,
      sources: [],
      status: "done" as const,
    }));
    dispatch({ type: "LOAD_SESSION", turns, sessionId });
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
      value={{ session, sendMessage, cancelTurn, setKnowledgeBase, setLLMSelection, setHints, loadSession, newSession }}
    >
      {children}
    </AgentChatContext.Provider>
  );
}

export function useAgentChat(): AgentChatContextValue {
  const ctx = useContext(AgentChatContext);
  if (!ctx) throw new Error("useAgentChat must be used within AgentChatProvider");
  return ctx;
}
```

Note: `getSession` in `web/lib/session-api.ts` returns a session object. Check what fields the backend returns for `turns` — the field names may differ from `user_content`/`assistant_content`. Open `web/lib/session-api.ts`, find `getSession`, and check the returned type. Adjust the `loadSession` mapping above to match the actual field names.

- [ ] **Step 2: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

Expected: no errors. Fix any type mismatches before continuing.

- [ ] **Step 3: Commit**

```bash
git add web/context/AgentChatContext.tsx
git commit -m "feat(v2): add AgentChatContext with WS orchestration"
```

---

## Task 3: AdvancedPanel

**Files:**
- Create: `web/components/agent/AdvancedPanel.tsx`

- [ ] **Step 1: Create `web/components/agent/AdvancedPanel.tsx`**

```tsx
"use client";

import { useTranslation } from "react-i18next";

const TOOLS = [
  { id: "brainstorm", label: "Brainstorm" },
  { id: "rag", label: "Knowledge Base" },
  { id: "web_search", label: "Web Search" },
  { id: "code_execution", label: "Code Execution" },
  { id: "reason", label: "Deep Reasoning" },
  { id: "paper_search", label: "Paper Search" },
] as const;

interface AdvancedPanelProps {
  hints: string[];
  onHintsChange: (hints: string[]) => void;
}

export function AdvancedPanel({ hints, onHintsChange }: AdvancedPanelProps) {
  const { t } = useTranslation();

  function toggle(toolId: string) {
    onHintsChange(
      hints.includes(toolId)
        ? hints.filter((h) => h !== toolId)
        : [...hints, toolId],
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
        {t("Tool hints — optional, agent still decides")}
      </p>
      <div className="flex flex-wrap gap-2">
        {TOOLS.map((tool) => {
          const active = hints.includes(tool.id);
          return (
            <button
              key={tool.id}
              type="button"
              onClick={() => toggle(tool.id)}
              className={[
                "rounded-full px-3 py-1 text-xs transition-colors",
                active
                  ? "bg-[var(--accent)] text-white"
                  : "bg-[var(--chip-bg,#f3f4f6)] text-[var(--muted)] hover:bg-[var(--chip-hover,#e5e7eb)] dark:bg-[#21262d] dark:hover:bg-[#30363d]",
              ].join(" ")}
            >
              {t(tool.label)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add web/components/agent/AdvancedPanel.tsx
git commit -m "feat(v2): add AdvancedPanel tool hints"
```

---

## Task 4: ComposerActions

**Files:**
- Create: `web/components/agent/ComposerActions.tsx`

- [ ] **Step 1: Check `KnowledgeBase` type in `web/lib/knowledge-api.ts`**

Open `web/lib/knowledge-api.ts`. Confirm the return type of `listKnowledgeBases()` — look for a type that has at minimum `id: string` and `name: string`. Note the exact interface name; use it in the import below. If no type is exported, add one.

- [ ] **Step 2: Create `web/components/agent/ComposerActions.tsx`**

```tsx
"use client";

import { useTranslation } from "react-i18next";
import { BookOpen, Send, Settings2, Square } from "lucide-react";
import type { AgentLLMSelection } from "@/lib/agent-chat-types";

// Adjust this import to match the actual exported type name from knowledge-api.ts
import type { KnowledgeBase } from "@/lib/knowledge-api";

interface ComposerActionsProps {
  knowledgeBases: KnowledgeBase[];
  activeKbId: string | null;
  llmSelection: AgentLLMSelection | null;
  hints: string[];
  advancedOpen: boolean;
  isStreaming: boolean;
  onKbChange: (id: string | null) => void;
  onAdvancedToggle: () => void;
  onSend: () => void;
  onCancel: () => void;
}

export function ComposerActions({
  knowledgeBases,
  activeKbId,
  hints,
  advancedOpen,
  isStreaming,
  onKbChange,
  onAdvancedToggle,
  onSend,
  onCancel,
}: ComposerActionsProps) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {/* KB selector */}
        <label className="relative flex items-center">
          <BookOpen
            size={10}
            className="pointer-events-none absolute left-2 text-[var(--accent)]"
          />
          <select
            className="appearance-none rounded-full bg-[var(--surface-2,#f3f4f6)] py-1 pl-5 pr-3 text-xs text-[var(--muted)] cursor-pointer hover:bg-[var(--surface-3,#e5e7eb)] focus:outline-none dark:bg-[#21262d] dark:hover:bg-[#30363d]"
            value={activeKbId ?? ""}
            onChange={(e) => onKbChange(e.target.value || null)}
            aria-label={t("Knowledge Base")}
          >
            <option value="">{t("KB: None")}</option>
            {knowledgeBases.map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name}
              </option>
            ))}
          </select>
        </label>

        {/* Advanced toggle */}
        <button
          type="button"
          onClick={onAdvancedToggle}
          className={[
            "flex items-center gap-1 rounded-full px-3 py-1 text-xs transition-colors",
            advancedOpen || hints.length > 0
              ? "border border-[var(--accent)] bg-[var(--accent-subtle,#dbeafe)] text-[var(--accent)] dark:bg-[#0d2136]"
              : "bg-[var(--surface-2,#f3f4f6)] text-[var(--muted)] hover:bg-[var(--surface-3,#e5e7eb)] dark:bg-[#21262d] dark:hover:bg-[#30363d]",
          ].join(" ")}
        >
          <Settings2 size={10} />
          {t("Advanced")}
          {hints.length > 0 && (
            <span className="ml-0.5 text-[10px]">({hints.length})</span>
          )}
        </button>
      </div>

      {/* Send / Cancel */}
      {isStreaming ? (
        <button
          type="button"
          onClick={onCancel}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-500 text-white hover:bg-red-600"
          aria-label={t("Cancel")}
        >
          <Square size={13} fill="white" />
        </button>
      ) : (
        <button
          type="button"
          onClick={onSend}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-white hover:opacity-90"
          aria-label={t("Send")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

Fix `KnowledgeBase` import if the type name differs in `knowledge-api.ts`.

- [ ] **Step 4: Commit**

```bash
git add web/components/agent/ComposerActions.tsx
git commit -m "feat(v2): add ComposerActions pill controls"
```

---

## Task 5: AgentComposer

**Files:**
- Create: `web/components/agent/AgentComposer.tsx`

- [ ] **Step 1: Check `ComposerInput` ref handle**

Open `web/components/chat/home/ComposerInput.tsx`. Find the `useImperativeHandle` call — note the exact type it exposes (likely `{ focus: () => void }` or similar). Use that type for `inputRef` below.

- [ ] **Step 2: Create `web/components/agent/AgentComposer.tsx`**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ComposerInput } from "@/components/chat/home/ComposerInput";
import { ComposerActions } from "@/components/agent/ComposerActions";
import { AdvancedPanel } from "@/components/agent/AdvancedPanel";
import { useAgentChat } from "@/context/AgentChatContext";
import { listKnowledgeBases } from "@/lib/knowledge-api";

// Adjust KnowledgeBase to match the actual exported type from knowledge-api.ts
import type { KnowledgeBase } from "@/lib/knowledge-api";

export function AgentComposer() {
  const { t } = useTranslation();
  const { session, sendMessage, cancelTurn, setKnowledgeBase, setHints } = useAgentChat();

  const [text, setText] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);

  // Match the exact type from ComposerInput's useImperativeHandle
  const inputRef = useRef<{ focus: () => void } | null>(null);

  useEffect(() => {
    listKnowledgeBases().then(setKbs).catch(console.error);
  }, []);

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || session.isStreaming) return;
    sendMessage({ content: trimmed });
    setText("");
    setAdvancedOpen(false);
    inputRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
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
          <ComposerInput
            ref={inputRef}
            value={text}
            onChange={setText}
            onKeyDown={handleKeyDown}
            placeholder={t("Ask anything — I'll use the right tools")}
            disabled={session.isStreaming}
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
```

Note: `ComposerInput` may use different prop names (`value`/`onChange`) — check its actual props and align. If it does not accept a `ref`, wrap it in a `forwardRef`-compatible pattern or replace with a plain `<textarea>`.

- [ ] **Step 3: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add web/components/agent/AgentComposer.tsx
git commit -m "feat(v2): add AgentComposer"
```

---

## Task 6: UserMessage

**Files:**
- Create: `web/components/agent/UserMessage.tsx`

- [ ] **Step 1: Create `web/components/agent/UserMessage.tsx`**

```tsx
import type { AgentTurn } from "@/lib/agent-chat-types";

interface UserMessageProps {
  turn: AgentTurn;
}

export function UserMessage({ turn }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-[var(--accent)] px-4 py-2.5 text-sm text-white">
        {turn.userContent}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/agent/UserMessage.tsx
git commit -m "feat(v2): add UserMessage bubble"
```

---

## Task 7: AgentStepTimeline

**Files:**
- Create: `web/components/agent/AgentStepTimeline.tsx`

- [ ] **Step 1: Create `web/components/agent/AgentStepTimeline.tsx`**

```tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Zap } from "lucide-react";
import type { StepEvent } from "@/lib/agent-chat-types";

const STEP_ICON: Record<string, string> = {
  thinking: "🧠",
  tool_call: "🔧",
  tool_result: "✓",
  stage_start: "▶",
  stage_end: "■",
  observation: "👁",
};

interface AgentStepTimelineProps {
  steps: StepEvent[];
  isStreaming: boolean;
}

export function AgentStepTimeline({ steps, isStreaming }: AgentStepTimelineProps) {
  const [expanded, setExpanded] = useState(false);

  if (steps.length === 0 && !isStreaming) return null;

  // Collect unique tool names from tool_call steps for the summary line
  const toolsUsed = [
    ...new Set(
      steps
        .filter((s) => s.type === "tool_call")
        .map((s) => s.label.split(":")[0].trim()),
    ),
  ];

  // Collapsed summary (shown once streaming ends)
  if (!isStreaming && steps.length > 0) {
    return (
      <div className="mb-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
        >
          <Zap size={11} className="text-[var(--accent)]" />
          <span>
            {toolsUsed.length > 0
              ? `Used ${toolsUsed.join(" · ")}`
              : `${steps.length} step${steps.length !== 1 ? "s" : ""}`}
          </span>
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </button>
        {expanded && (
          <div className="mt-2 space-y-1 pl-4 border-l border-[var(--border)]">
            {steps.map((step) => <StepRow key={step.id} step={step} />)}
          </div>
        )}
      </div>
    );
  }

  // Live view during streaming
  return (
    <div className="mb-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="space-y-1.5">
        {steps.map((step, i) => (
          <StepRow
            key={step.id}
            step={step}
            isActive={i === steps.length - 1 && isStreaming}
          />
        ))}
        {isStreaming && steps.length === 0 && (
          <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent)]" />
            Thinking…
          </div>
        )}
      </div>
    </div>
  );
}

function StepRow({ step, isActive }: { step: StepEvent; isActive?: boolean }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="mt-0.5 shrink-0 text-[11px]">
        {isActive ? (
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent)]" />
        ) : (
          STEP_ICON[step.type] ?? "·"
        )}
      </span>
      <span className={step.done ? "text-[var(--muted)]" : "text-[var(--foreground)]"}>
        {step.label}
      </span>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add web/components/agent/AgentStepTimeline.tsx
git commit -m "feat(v2): add AgentStepTimeline"
```

---

## Task 8: RichOutputEmbed + AgentMessage

**Files:**
- Create: `web/components/agent/RichOutputEmbed.tsx`
- Create: `web/components/agent/AgentMessage.tsx`

- [ ] **Step 1: Check existing viewer props**

Open each file and note the exact props they accept:
- `web/components/quiz/QuizViewer.tsx` — what props does `QuizViewer` accept?
- `web/components/math-animator/MathAnimatorViewer.tsx`
- `web/components/visualize/VisualizationViewer.tsx`
- `web/components/research/ResearchOutlineEditor.tsx`

The `richOutputData` passed from the context contains the `metadata` object from the WS `result` event. Each viewer likely expects a specific shape. Note any required props and pass them below.

- [ ] **Step 2: Check `AssistantResponse` props**

Open `web/components/common/AssistantResponse.tsx`. Note the exact prop names for passing content (likely `content: string` or `markdown: string`).

- [ ] **Step 3: Create `web/components/agent/RichOutputEmbed.tsx`**

```tsx
"use client";

import dynamic from "next/dynamic";
import type { RichOutputType } from "@/lib/agent-chat-types";

// Lazy-load each viewer — adjust the named export if the component uses a default export
const QuizViewer = dynamic(
  () => import("@/components/quiz/QuizViewer").then((m) => m.QuizViewer ?? m.default),
  { ssr: false },
);
const MathAnimatorViewer = dynamic(
  () => import("@/components/math-animator/MathAnimatorViewer").then((m) => m.MathAnimatorViewer ?? m.default),
  { ssr: false },
);
const VisualizationViewer = dynamic(
  () => import("@/components/visualize/VisualizationViewer").then((m) => m.VisualizationViewer ?? m.default),
  { ssr: false },
);
const ResearchOutlineEditor = dynamic(
  () => import("@/components/research/ResearchOutlineEditor").then((m) => m.ResearchOutlineEditor ?? m.default),
  { ssr: false },
);

interface RichOutputEmbedProps {
  richOutputType: RichOutputType;
  richOutputData: unknown;
  sessionId: string | null;
  turnId: string;
}

export function RichOutputEmbed({
  richOutputType,
  richOutputData,
  sessionId,
  turnId,
}: RichOutputEmbedProps) {
  if (!richOutputType || !richOutputData) return null;

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-[var(--accent-subtle,#dbeafe)] dark:border-[#1c3a5e]">
      {/* Pass props that match each viewer's interface exactly.
          After checking each component in step 1, replace the spread below
          with the actual required props. */}
      {richOutputType === "quiz" && (
        <QuizViewer data={richOutputData} sessionId={sessionId} turnId={turnId} />
      )}
      {richOutputType === "math_animator" && (
        <MathAnimatorViewer data={richOutputData} />
      )}
      {richOutputType === "visualize" && (
        <VisualizationViewer data={richOutputData} />
      )}
      {richOutputType === "deep_research" && (
        <ResearchOutlineEditor data={richOutputData} sessionId={sessionId} />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create `web/components/agent/AgentMessage.tsx`**

```tsx
import type { AgentTurn, StepEvent } from "@/lib/agent-chat-types";
import { AgentStepTimeline } from "@/components/agent/AgentStepTimeline";
import { AssistantResponse } from "@/components/common/AssistantResponse";
import { RichOutputEmbed } from "@/components/agent/RichOutputEmbed";

interface AgentMessageProps {
  turn: AgentTurn;
  activeSteps: StepEvent[];
  isStreaming: boolean;
  sessionId: string | null;
}

export function AgentMessage({ turn, activeSteps, isStreaming, sessionId }: AgentMessageProps) {
  const steps = turn.status === "streaming" ? activeSteps : turn.steps;
  const showTimeline = steps.length > 0 || (turn.status === "streaming" && isStreaming);

  return (
    <div className="flex flex-col gap-1">
      {showTimeline && (
        <AgentStepTimeline
          steps={steps}
          isStreaming={turn.status === "streaming" && isStreaming}
        />
      )}

      {turn.assistantContent && (
        <div className="rounded-2xl rounded-tl-sm bg-[var(--surface)] px-4 py-3 text-sm text-[var(--foreground)]">
          {/* Adjust prop name to match AssistantResponse — may be `content`, `markdown`, or `message` */}
          <AssistantResponse content={turn.assistantContent} />
        </div>
      )}

      {turn.richOutputType && (
        <RichOutputEmbed
          richOutputType={turn.richOutputType}
          richOutputData={turn.richOutputData}
          sessionId={sessionId}
          turnId={turn.id}
        />
      )}

      {turn.status === "error" && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600 dark:bg-red-950 dark:text-red-400">
          {turn.errorMessage ?? "Something went wrong. Please try again."}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

Fix prop mismatches with the existing viewer components and `AssistantResponse`.

- [ ] **Step 6: Commit**

```bash
git add web/components/agent/RichOutputEmbed.tsx web/components/agent/AgentMessage.tsx
git commit -m "feat(v2): add RichOutputEmbed and AgentMessage"
```

---

## Task 9: MessageFeed

**Files:**
- Create: `web/components/agent/MessageFeed.tsx`

- [ ] **Step 1: Create `web/components/agent/MessageFeed.tsx`**

```tsx
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session.turns.length, session.activeSteps.length]);

  if (session.turns.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
        <p className="text-lg font-medium text-[var(--foreground)]">
          {t("Ask anything — I'll use the right tools")}
        </p>
        <p className="text-sm text-[var(--muted)]">
          Search the web, query knowledge bases, run code, or generate quizzes and animations — automatically.
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
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add web/components/agent/MessageFeed.tsx
git commit -m "feat(v2): add MessageFeed"
```

---

## Task 10: V2Sidebar + Route Scaffold

**Files:**
- Create: `web/components/agent/V2Sidebar.tsx`
- Create: `web/app/(v2)/layout.tsx`
- Create: `web/app/(v2)/chat/[[...sessionId]]/page.tsx` (stub)

- [ ] **Step 1: Create `web/components/agent/V2Sidebar.tsx`**

```tsx
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

  // Refresh session list whenever a new session is assigned by the server
  useEffect(() => { void refresh(); }, [refresh, session.sessionId]);

  const handleNewChat = () => {
    newSession();
    router.push("/v2/chat");
  };

  const handleSelectSession = useCallback(
    (sessionId: string) => { router.push(`/v2/chat/${sessionId}`); },
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
```

- [ ] **Step 2: Create `web/app/(v2)/layout.tsx`**

```tsx
import { AgentChatProvider } from "@/context/AgentChatContext";
import { V2Sidebar } from "@/components/agent/V2Sidebar";

export default function V2Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <AgentChatProvider>
      <div className="flex h-screen overflow-hidden">
        <V2Sidebar />
        <main className="flex-1 overflow-hidden bg-[var(--background)]">
          {children}
        </main>
      </div>
    </AgentChatProvider>
  );
}
```

- [ ] **Step 3: Create stub page**

Create `web/app/(v2)/chat/[[...sessionId]]/page.tsx`:

```tsx
export default function V2ChatPage() {
  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-sm text-[var(--muted)]">V2 chat — loading…</p>
    </div>
  );
}
```

- [ ] **Step 4: Start dev server and verify the route renders**

```
cd web && npm run dev -- -p 3782
```

Navigate to `http://localhost:3782/v2/chat`. Expected: sidebar appears, stub text shows in the main area. No console errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/agent/V2Sidebar.tsx web/app/(v2)/layout.tsx "web/app/(v2)/chat/[[...sessionId]]/page.tsx"
git commit -m "feat(v2): scaffold (v2) route group with layout and stub page"
```

---

## Task 11: AgentChatPage

**Files:**
- Modify: `web/app/(v2)/chat/[[...sessionId]]/page.tsx`

- [ ] **Step 1: Replace stub with full page**

```tsx
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
```

- [ ] **Step 2: Verify golden path in dev server**

```
cd web && npm run dev -- -p 3782
```

Navigate to `http://localhost:3782/v2/chat`.

1. Empty state message renders in center.
2. Type a question, press Enter — user bubble appears immediately.
3. Step timeline shows "Thinking…" pulse while the backend processes.
4. Steps appear one by one as the agent works.
5. Response streams in below the timeline.
6. Once done, timeline collapses to "Used …" summary line.
7. URL in the browser updates to `/v2/chat/<sessionId>`.

- [ ] **Step 3: Verify TypeScript compiles**

```
cd web && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add "web/app/(v2)/chat/[[...sessionId]]/page.tsx"
git commit -m "feat(v2): complete AgentChatPage"
```

---

## Task 12: Navigation updates

**Files:**
- Modify: `web/components/sidebar/SidebarShell.tsx` (line 35)
- Modify: `web/app/(workspace)/page.tsx`

- [ ] **Step 1: Update Chat nav href in `SidebarShell.tsx`**

On line 35, change:

```typescript
// Before
{ href: "/chat", label: "Chat", icon: MessageSquare },

// After
{ href: "/v2/chat", label: "Chat", icon: MessageSquare },
```

- [ ] **Step 2: Update root redirect in `web/app/(workspace)/page.tsx`**

Change both `/chat` references:

```typescript
// Before
let target = sessionId ? `/chat/${sessionId}` : "/chat";

// After
let target = sessionId ? `/v2/chat/${sessionId}` : "/v2/chat";
```

- [ ] **Step 3: Verify navigation in dev server**

- Open `http://localhost:3782/` — expected: redirects to `/v2/chat`.
- Click "New Chat" in sidebar — expected: navigates to `/v2/chat`.
- Click the Chat icon in the sidebar nav — expected: navigates to `/v2/chat`.
- Navigate directly to `http://localhost:3782/chat` — expected: old v1 interface still loads unchanged.
- Navigate to `/agents`, `/co-writer`, `/book`, `/knowledge`, `/space` — expected: all load normally.

- [ ] **Step 4: Commit**

```bash
git add web/components/sidebar/SidebarShell.tsx web/app/(workspace)/page.tsx
git commit -m "feat(v2): update Chat nav and root redirect to /v2/chat"
```

---

## Task 13: i18n keys

**Files:**
- Modify: `web/locales/en/app.json`
- Modify: `web/locales/zh/app.json`

- [ ] **Step 1: Add English keys to `web/locales/en/app.json`**

Append to the JSON object (preserve all existing keys):

```json
"Ask anything — I'll use the right tools": "Ask anything — I'll use the right tools",
"Tool hints — optional, agent still decides": "Tool hints — optional, agent still decides",
"KB: None": "KB: None",
"Knowledge Base": "Knowledge Base",
"Advanced": "Advanced",
"Brainstorm": "Brainstorm",
"Web Search": "Web Search",
"Code Execution": "Code Execution",
"Deep Reasoning": "Deep Reasoning",
"Paper Search": "Paper Search",
"Cancel": "Cancel",
"Send": "Send"
```

Check first — some of these keys (e.g. "Cancel", "Knowledge Base") may already exist in `app.json`. Only add keys that are missing.

- [ ] **Step 2: Add Chinese keys to `web/locales/zh/app.json`**

Append the same keys with Chinese values:

```json
"Ask anything — I'll use the right tools": "随时提问，我会自动选择合适的工具",
"Tool hints — optional, agent still decides": "工具提示 — 可选，AI 仍会自行决定",
"KB: None": "知识库：无",
"Knowledge Base": "知识库",
"Advanced": "高级",
"Brainstorm": "头脑风暴",
"Web Search": "网络搜索",
"Code Execution": "代码执行",
"Deep Reasoning": "深度推理",
"Paper Search": "论文搜索",
"Cancel": "取消",
"Send": "发送"
```

Again, only add keys that are missing from the existing file.

- [ ] **Step 3: Verify i18n parity**

```
cd web && npm run i18n:parity
```

Expected: no missing-key errors reported.

- [ ] **Step 4: Commit**

```bash
git add web/locales/en/app.json web/locales/zh/app.json
git commit -m "feat(v2): add i18n keys for v2 agent chat"
```

---

## Task 14: Final smoke test

- [ ] **Step 1: Start the full app**

```
cd D:/opensource/DeepTutor
python scripts/start_web.py
```

Wait for "Application startup complete" (backend on port 8001) and "✓ Ready" (frontend on port 3782).

- [ ] **Step 2: Golden path — send a message**

1. Open `http://localhost:3782` — confirm redirect to `/v2/chat`.
2. Type a question (e.g. "Explain the chain rule in calculus") and press Enter.
3. User bubble appears immediately.
4. Step timeline shows "Thinking…" pulse, then steps appear as agent works.
5. Response streams in below the steps.
6. Steps collapse to summary ("Used reason" or similar) once done.
7. Click the summary — it expands to show individual steps.

- [ ] **Step 3: Advanced panel**

1. Click "⚙ Advanced" — tool hint chips appear.
2. Toggle "Web Search" — chip highlights.
3. Send a message — panel closes after send. Step timeline should show `web_search` tool being used.

- [ ] **Step 4: Session persistence**

1. Refresh the page — URL should still contain the session ID.
2. Previous messages should reload.

- [ ] **Step 5: Old routes still work**

Navigate to `/chat`, `/agents`, `/co-writer`, `/book`, `/knowledge`, `/space`, `/settings` — all load correctly.

- [ ] **Step 6: TypeScript + lint clean**

```
cd web && npx tsc --noEmit && npm run lint
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat(v2): v2 agent chat — all tasks complete"
```
