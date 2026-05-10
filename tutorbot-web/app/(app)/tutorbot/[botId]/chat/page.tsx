"use client";

import { useParams } from "next/navigation";
import BotChatView from "@/components/tutorbot/chat/BotChatView";

export default function BotChatPage() {
  const { botId } = useParams<{ botId: string }>();

  return (
    <div className="h-[calc(100vh-0px)]">
      <BotChatView botId={botId} />
    </div>
  );
}
