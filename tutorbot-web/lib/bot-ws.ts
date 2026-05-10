import { wsUrl } from "./api";

export type BotMessage =
  | { type: "thinking"; content: string }
  | { type: "content"; content: string }
  | { type: "done" }
  | { type: "error"; content: string }
  | { type: "proactive"; content: string };

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
        }));
      }
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
