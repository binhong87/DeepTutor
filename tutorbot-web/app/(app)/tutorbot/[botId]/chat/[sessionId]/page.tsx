"use client";

import { useParams } from "next/navigation";
import BotChatView from "@/components/tutorbot/chat/BotChatView";

export default function BotSessionChatPage() {
  const { botId, sessionId } = useParams<{ botId: string; sessionId: string }>();

  return (
    <div className="h-[calc(100vh-0px)]">
      <BotChatView botId={botId} sessionId={sessionId} />
    </div>
  );
}
