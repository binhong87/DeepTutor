import { wsUrl } from "./api";

export type LessonStepStatus = "pending" | "in_progress" | "done" | "skipped";

export interface LessonStep {
  id: string;
  phase: string;
  goal: string;
  requires?: string[];
  tools_hint?: string[];
  status?: LessonStepStatus;
  output_summary?: string;
}

export interface LessonPlan {
  topic: string;
  steps: LessonStep[];
  current_step_id?: string | null;
}

export type BotMessage =
  | { type: "thinking"; content: string }
  | { type: "content"; content: string }
  | { type: "done" }
  | { type: "error"; content: string }
  | { type: "proactive"; content: string }
  | { type: "lesson_plan"; plan: LessonPlan };

export type BotChatTurn = {
  id: string;
  role: "user" | "bot";
  content: string;
  thinking: string[];
  status: "thinking" | "done" | "error";
  timestamp: number;
};

let _turnCounter = 0;

export function nextTurnId(): string {
  _turnCounter += 1;
  return `turn-${_turnCounter}`;
}

export function connectBotWS(
  botId: string,
  onTurnUpdate: (turnId: string, updater: (turn: BotChatTurn) => BotChatTurn) => void,
  signal: AbortSignal,
  onLessonPlan?: (plan: LessonPlan) => void,
): WebSocket {
  const socket = new WebSocket(wsUrl(`/api/v1/tutorbot/${botId}/ws`));

  let currentTurnId: string | null = null;

  socket.addEventListener("message", (event) => {
    let msg: BotMessage;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }

    if (msg.type === "proactive") {
      // Proactive messages from the bot (e.g., scheduled reminders)
      return;
    }

    if (msg.type === "lesson_plan") {
      onLessonPlan?.(msg.plan);
      return;
    }

    if (msg.type === "error") {
      if (currentTurnId) {
        onTurnUpdate(currentTurnId, (t) => ({ ...t, status: "error", content: t.content || msg.content }));
        currentTurnId = null;
      }
      return;
    }

    if (msg.type === "thinking") {
      if (!currentTurnId) {
        currentTurnId = nextTurnId();
        onTurnUpdate(currentTurnId, (t) => ({
          ...t,
          role: "bot",
          content: "",
          thinking: [...t.thinking, msg.content],
          status: "thinking",
          timestamp: Date.now(),
        }));
      } else {
        onTurnUpdate(currentTurnId, (t) => ({
          ...t,
          thinking: [...t.thinking, msg.content],
        }));
      }
      return;
    }

    if (msg.type === "content") {
      // `content` carries the final assistant response for the turn. Mark the
      // turn done here (in both the new-turn and existing-turn branches) so a
      // missed `{type:"done"}` — e.g. uvicorn reload, network blip, or the
      // backend short-circuiting after a DIRECT_RESULT tool — does not leave
      // the spinner running with the content already visible.
      if (!currentTurnId) {
        currentTurnId = nextTurnId();
        onTurnUpdate(currentTurnId, (t) => ({
          ...t,
          role: "bot",
          content: msg.content,
          thinking: [],
          status: "done",
          timestamp: Date.now(),
        }));
      } else {
        onTurnUpdate(currentTurnId, (t) => ({
          ...t,
          content: msg.content,
          thinking: t.thinking,
          status: "done",
        }));
      }
      currentTurnId = null;
      return;
    }

    if (msg.type === "done") {
      if (currentTurnId) {
        onTurnUpdate(currentTurnId, (t) => ({ ...t, status: "done" }));
        currentTurnId = null;
      }
    }
  });

  signal.addEventListener("abort", () => {
    socket.close(1000, "user navigated away");
  });

  return socket;
}
