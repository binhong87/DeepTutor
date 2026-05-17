"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { listBotSessions } from "@/lib/tutorbot-api";

export default function BotChatRedirectPage() {
  const { botId } = useParams<{ botId: string }>();
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    listBotSessions(botId)
      .then((rows) => {
        if (cancelled) return;
        const def = rows.find((r) => r.status === "default");
        if (def) router.replace(`/tutorbot/${botId}/chat/${def.id}`);
      })
      .catch(() => {
        /* leave the spinner — user can retry by navigating */
      });
    return () => {
      cancelled = true;
    };
  }, [botId, router]);

  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
    </div>
  );
}
