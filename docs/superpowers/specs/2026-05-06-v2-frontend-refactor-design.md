# V2 Frontend Refactor — Design Spec

**Date:** 2026-05-06  
**Status:** Approved  
**Scope:** New `(v2)` route group for a unified agent chat experience alongside the existing frontend.

---

## Background

DeepTutor's current chat page (`web/app/(workspace)/chat/`) requires users to manually select a *capability* (deep_solve, deep_question, math_animator, etc.) and toggle individual *tools* (rag, web_search, code_execution, reason, paper_search, brainstorm) before each message. This creates friction and cognitive overhead. The goal is a single unified chat interface where the agent automatically selects and uses the right tools, producing rich outputs when appropriate.

The existing frontend (`/chat`, `/agents`, `/co-writer`, `/book`, `/knowledge`, `/space/*`, `/settings`) is preserved unchanged. The v2 chat becomes the new default entry point.

---

## Goals

1. Remove manual capability/tool switching from the main chat UX.
2. Agent automatically selects tools per turn; all tools are enabled by default.
3. User retains lightweight controls: KB selector, model selector, optional tool hints.
4. Agent can still produce rich outputs (quiz, math animation, visualization, research) — triggered automatically by intent.
5. Centered-column layout with live streaming step visibility inside the response bubble.
6. Clean component architecture: no god components, no prop-drilling chains.

---

## Non-Goals

- Replacing or modifying `/agents`, `/co-writer`, `/book`, `/knowledge`, `/space/*`. These stay as-is.
- Changing the WebSocket protocol or backend session model.
- A mobile-specific redesign (responsive is fine, mobile-first is out of scope).

---

## Routes & Navigation

### New route group

```
web/app/(v2)/
├── layout.tsx                         ← V2ShellLayout (AgentChatProvider + SidebarShell)
└── chat/
    └── [[...sessionId]]/
        └── page.tsx                   ← AgentChatPage
```

- New chat lives at `/v2/chat` (new session) and `/v2/chat/[sessionId]` (existing session).
- Root `/` redirect updated: points to `/v2/chat` instead of `/chat`.
- `SidebarShell` PRIMARY_NAV: "Chat" entry updated from `/chat` → `/v2/chat`.
- Old `/chat/[[...sessionId]]` remains fully functional — no routes removed.
- When a new session receives a server-assigned `sessionId` via the `session` WS event, `AgentChatPage` calls `router.replace("/v2/chat/<sessionId>")` so the URL reflects the session (mirrors v1 behaviour).
- If the user clicks a v1 session from the sidebar session list, they land on `/v2/chat/[sessionId]`. The v2 context loads the session via `getSession()` and renders it; tool/capability metadata from v1 is ignored (not present in the v2 state shape).

### Sidebar

The existing `SidebarShell` is reused with one change: the Chat nav entry points to `/v2/chat`. Session list beneath Chat reflects v2 sessions (sourced from `AgentChatContext`). All other nav entries (TutorBot, Co-Writer, Book, Knowledge, Space, Settings) are unchanged.

---

## Component Architecture

```
(v2)/layout.tsx
└── V2ShellLayout
      ├── SidebarShell  (updated Chat link)
      └── AgentChatPage               (~100 lines — orchestration only)
            ├── MessageFeed
            │     └── [per turn]
            │           ├── UserMessage
            │           └── AgentMessage
            │                 ├── AgentStepTimeline   ← live steps during streaming
            │                 ├── AssistantResponse   ← reused from web/components/common/
            │                 └── RichOutputEmbed     ← quiz / math-anim / visualize / research
            ├── AgentComposer
            │     ├── ComposerInput        ← reused web/components/chat/home/ComposerInput.tsx
            │     ├── ComposerActions      ← KB selector + model selector + Advanced pill
            │     └── AdvancedPanel        ← collapsible tool hint toggles
            └── FilePreviewDrawer          ← reused as-is
```

### Component responsibilities

**`AgentChatPage`** — owns session ID (from URL param), scroll ref, and submit handler. No UI rendering. Reads from `AgentChatContext`, dispatches actions.

**`MessageFeed`** — renders the ordered list of turns. Handles auto-scroll via `useChatAutoScroll` (reused hook). Each turn renders one `UserMessage` + one `AgentMessage`.

**`AgentMessage`** — renders a single assistant turn. Contains three sub-sections stacked vertically:
1. `AgentStepTimeline` — visible during streaming, collapses to a single summary line (e.g. "Used reason · math_animator") on completion.
2. `AssistantResponse` — existing markdown/KaTeX renderer, reused without modification.
3. `RichOutputEmbed` — conditionally rendered when the turn includes a rich output (quiz, math animation, visualization, research outline). Each embed type is lazy-loaded.

**`AgentStepTimeline`** — receives `steps: StepEvent[]` and `isStreaming: boolean`. During streaming, renders each step as it arrives with a live indicator on the current step. On completion, collapses to a compact summary. Steps come from the WebSocket `stage_start`, `stage_end`, `thinking`, `tool_call`, `tool_result`, `observation` events.

**`AgentComposer`** — the input bar. Centered, max-width ~760px matching the message column.
- `ComposerInput`: auto-resize textarea (reused).
- `ComposerActions`: a row of pill-shaped chips below the textarea — KB selector, model selector, "⚙ Advanced" toggle. Only these three controls visible at rest.
- `AdvancedPanel`: expands inline below `ComposerActions` when Advanced is toggled. Shows tool hint checkboxes (brainstorm, rag, web_search, code_execution, reason, paper_search). Hints are soft preferences — the agent can still use any tool. Panel closes after the message is sent.

**`RichOutputEmbed`** — a unified embed shell that lazy-loads the correct viewer:
- `QuizViewer` (reused) when `richOutputType === "quiz"`
- `MathAnimatorViewer` (reused) when `richOutputType === "math_animator"`
- `VisualizationViewer` (reused) when `richOutputType === "visualize"`
- `ResearchOutlineEditor` (reused) when `richOutputType === "deep_research"`

---

## State & Context

### `AgentChatContext` (`web/context/AgentChatContext.tsx`)

New context, independent of `UnifiedChatContext`. Does not modify or extend the existing context.

```ts
type StepEvent = {
  type: "stage_start" | "stage_end" | "thinking" | "tool_call" | "tool_result" | "observation"
  label: string
  detail?: string
  timestamp: number
}

type AgentTurn = {
  id: string
  userContent: string
  userAttachments: Attachment[]
  assistantContent: string
  steps: StepEvent[]
  richOutputType: "quiz" | "math_animator" | "visualize" | "deep_research" | null
  richOutputData: unknown
  sources: SourceRef[]
  status: "streaming" | "done" | "error"
}

type AgentSession = {
  sessionId: string | null          // null = draft (not yet server-assigned)
  turns: AgentTurn[]
  activeSteps: StepEvent[]          // cleared after each turn completes
  knowledgeBaseId: string | null
  llmSelection: LLMSelection | null
  isStreaming: boolean
  status: "idle" | "streaming" | "error"
}
```

**Reducer actions:** `NEW_TURN`, `STREAM_STEP`, `STREAM_CONTENT`, `STREAM_RICH_OUTPUT`, `STREAM_SOURCES`, `STREAM_DONE`, `STREAM_ERROR`, `BIND_SESSION`, `LOAD_SESSION`, `SET_KB`, `SET_LLM`, `SET_HINTS`.

**WebSocket:** Reuses `UnifiedWSClient` from `web/lib/unified-ws.ts` — heartbeat, reconnect, and backoff are already correct. `AgentChatContext` instantiates its own `UnifiedWSClient` instances (stored in a ref map, not in React state), exactly as `UnifiedChatContext` does.

**Session persistence:** Reuses `session-api.ts` (`listSessions`, `getSession`, `deleteSession`). Sessions created via v2 appear in the same session list as v1 sessions (same backend store). The sidebar session list shows both.

**Storage:** `knowledgeBaseId` and `llmSelection` are persisted to `localStorage` with keys prefixed `deeptutor-v2-` to avoid colliding with v1.

---

## Composer Controls

### At rest
- Textarea placeholder: "Ask anything — I'll use the right tools"
- Below textarea: `[◉ KB: None ▾]  [✦ Model ▾]  [⚙ Advanced]`  `[↑ Send]`

### KB selector
Dropdown populated by `listKnowledgeBases()`. Options: "None" + one entry per KB. Active selection shown in the pill. When a KB is selected, RAG is implicitly available as a tool.

### Model selector
Populated by `listLLMOptions()`. Groups by provider. Mirrors existing `ModelSelector` behaviour, reuses the component.

### Advanced panel (collapsed by default)
Renders below `ComposerActions` when opened. Contains:
- Section label: "Tool hints — optional, agent still decides"
- Checkboxes for each tool: brainstorm, rag, web_search, code_execution, reason, paper_search
- Checked = hinted (sent as `hints` in `start_turn`). All start unchecked.
- Panel auto-closes after send.

---

## Backend Integration

### WebSocket `start_turn` payload (v2)

```json
{
  "type": "start_turn",
  "capability": "",
  "tools": ["brainstorm", "rag", "web_search", "code_execution", "reason", "paper_search"],
  "knowledge_base_id": "<string | null>",
  "llm": { "provider": "...", "model": "..." },
  "hints": ["web_search"],
  "content": "<user message>",
  "attachments": []
}
```

All tools are always passed as enabled. `hints` carries the optional user preferences. The backend chat capability's LLM decides which tools to call. No backend changes required for the basic experience.

### Rich output via intent

When the user's message implies a rich output ("quiz me", "animate this", "visualize the concept", "research this topic"), the backend switches to the matching capability internally and returns a `session` event with the capability name. The frontend reads `session.capability` on the first `session` event of a turn and sets `richOutputType` accordingly. The matching viewer renders when the response is complete.

This requires one backend addition: exposing `quiz`, `math_animator`, `visualize`, and `deep_research` as tool-callable capabilities from within the default chat capability. This is a single backend PR that runs in parallel with the frontend work.

### Events consumed by `AgentChatContext`

| Event | Action |
|---|---|
| `session` | `BIND_SESSION` — stores server-assigned `sessionId`; reads `capability` for `richOutputType` |
| `stage_start` | `STREAM_STEP` — adds step to `activeSteps` |
| `stage_end` | `STREAM_STEP` — marks step complete |
| `thinking` | `STREAM_STEP` — adds thinking step |
| `tool_call` | `STREAM_STEP` — adds tool call step with detail |
| `tool_result` | `STREAM_STEP` — updates step with result summary |
| `content` | `STREAM_CONTENT` — appends to `assistantContent` |
| `sources` | `STREAM_SOURCES` — stores source refs |
| `result` | `STREAM_RICH_OUTPUT` — stores rich output data |
| `done` | `STREAM_DONE` — finalises turn, moves `activeSteps` into turn, clears streaming state |
| `error` | `STREAM_ERROR` |

---

## File Map

### New files

| Path | Purpose |
|---|---|
| `web/app/(v2)/layout.tsx` | V2ShellLayout — wraps AgentChatProvider + SidebarShell |
| `web/app/(v2)/chat/[[...sessionId]]/page.tsx` | AgentChatPage |
| `web/context/AgentChatContext.tsx` | New context + reducer + WS orchestration |
| `web/components/agent/MessageFeed.tsx` | Scrollable turn list |
| `web/components/agent/UserMessage.tsx` | User bubble |
| `web/components/agent/AgentMessage.tsx` | Assistant bubble container |
| `web/components/agent/AgentStepTimeline.tsx` | Live step stream + collapse |
| `web/components/agent/RichOutputEmbed.tsx` | Unified lazy-load shell for rich viewers |
| `web/components/agent/AgentComposer.tsx` | Composer bar shell |
| `web/components/agent/ComposerActions.tsx` | KB + model + Advanced pills |
| `web/components/agent/AdvancedPanel.tsx` | Collapsible tool hint panel |

### Modified files

| Path | Change |
|---|---|
| `web/components/sidebar/SidebarShell.tsx` | Update Chat nav entry href: `/chat` → `/v2/chat` |
| `web/app/(workspace)/page.tsx` | Update root redirect: `/chat` → `/v2/chat` |
| `web/locales/en/app.json` | Add i18n keys for new UI strings |
| `web/locales/zh/app.json` | Add i18n keys (Chinese) |

### Reused without modification

- `web/lib/unified-ws.ts` — WebSocket client
- `web/lib/session-api.ts` — session REST
- `web/lib/knowledge-api.ts` — KB REST
- `web/lib/llm-options.ts` — model list
- `web/components/chat/home/ComposerInput.tsx` — textarea
- `web/components/chat/home/ModelSelector.tsx` — model dropdown
- `web/components/chat/preview/FilePreviewDrawer.tsx` — file preview
- `web/components/common/AssistantResponse.tsx` — markdown renderer
- `web/components/quiz/QuizViewer.tsx`
- `web/components/math-animator/MathAnimatorViewer.tsx`
- `web/components/visualize/VisualizationViewer.tsx`
- `web/components/research/ResearchOutlineEditor.tsx`
- `web/hooks/useChatAutoScroll.ts`
- `web/context/AppShellContext.tsx`

---

## i18n

All new UI strings added to `locales/en/app.json` and `locales/zh/app.json`. Key new strings:
- Composer placeholder, Advanced panel label, tool hint labels, step timeline labels (thinking, searching, generating…), empty state.

---

## Build Sequence

1. `AgentChatContext` + WS wiring (no UI, fully testable)
2. `AgentComposer` (static, no context needed)
3. `AgentMessage` + `AgentStepTimeline` (with mock step data)
4. `MessageFeed` + `UserMessage`
5. `RichOutputEmbed` (wire in existing viewers)
6. `AgentChatPage` — connect all pieces
7. `(v2)/layout.tsx` + route group scaffold
8. Sidebar nav update + root redirect
9. i18n keys
10. Backend PR: intent-driven rich output tool invocation (parallel, not blocking frontend)
