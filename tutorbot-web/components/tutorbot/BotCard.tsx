"use client";

import Link from "next/link";
import { MessageCircle, Settings, Bot, Play, Square } from "lucide-react";
import type { TutorBotSummary } from "@/lib/tutorbot-api";

function BotStatusBadge({ running }: { running: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        running
          ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
          : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${running ? "bg-green-500" : "bg-gray-400"}`} />
      {running ? "Running" : "Stopped"}
    </span>
  );
}

export default function BotCard({
  bot,
  onStop,
}: {
  bot: TutorBotSummary;
  onStop?: (botId: string) => void;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-5 hover:shadow-sm transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--primary)]/10">
            <Bot className="h-5 w-5 text-[var(--primary)]" />
          </div>
          <div>
            <h3 className="font-medium text-[var(--foreground)] leading-tight">{bot.name}</h3>
            {bot.description && (
              <p className="text-xs text-[var(--muted-foreground)] mt-0.5 line-clamp-1">{bot.description}</p>
            )}
          </div>
        </div>
        <BotStatusBadge running={bot.running} />
      </div>

      <div className="flex items-center gap-2 pt-3 border-t border-[var(--border)]">
        <Link
          href={`/tutorbot/${bot.bot_id}/chat`}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90 transition-opacity"
        >
          <MessageCircle className="h-3.5 w-3.5" />
          Chat
        </Link>
        <Link
          href={`/tutorbot/${bot.bot_id}/settings`}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
        >
          <Settings className="h-3.5 w-3.5" />
          Settings
        </Link>
        <div className="flex-1" />
        {bot.running ? (
          <button
            onClick={() => onStop?.(bot.bot_id)}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium border border-red-200 text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950 transition-colors"
          >
            <Square className="h-3.5 w-3.5" />
            Stop
          </button>
        ) : (
          <Link
            href={`/tutorbot/${bot.bot_id}/chat`}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium border border-green-200 text-green-600 hover:bg-green-50 dark:border-green-800 dark:text-green-400 dark:hover:bg-green-950 transition-colors"
          >
            <Play className="h-3.5 w-3.5" />
            Start
          </Link>
        )}
      </div>
    </div>
  );
}
