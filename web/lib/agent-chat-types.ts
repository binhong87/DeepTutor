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

// Matches backend LLM profile wire format (snake_case intentional)
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
            ? { ...t, status: "done", steps: [...state.activeSteps] }
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
            ? { ...t, status: "error", errorMessage: action.message, steps: [...state.activeSteps] }
            : t,
        ),
      };

    case "BIND_SESSION": {
      const result: AgentSession = {
        ...state,
        sessionId: action.sessionId,
      };
      if (action.richOutputType !== undefined) {
        result.turns = state.turns.map((t, i) =>
          i === state.turns.length - 1
            ? { ...t, richOutputType: action.richOutputType! }
            : t,
        );
      }
      return result;
    }

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
