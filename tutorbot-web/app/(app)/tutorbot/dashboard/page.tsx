"use client";

import Link from "next/link";
import { Bot, Plus, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useTutorBots } from "@/context/TutorBotContext";
import BotCard from "@/components/tutorbot/BotCard";

export default function DashboardPage() {
  const { isAuthenticated, status, loading: authLoading } = useAuth();
  const { bots, loading: botsLoading, error, stopBot } = useTutorBots();

  if (authLoading || botsLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--foreground)]">Your TutorBots</h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {isAuthenticated && status?.username
              ? `Logged in as ${status.username}`
              : "Manage your AI tutoring agents"}
          </p>
        </div>
        <Link
          href="/tutorbot/boarding"
          className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 transition-opacity"
        >
          <Plus className="h-4 w-4" />
          Create New Bot
        </Link>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400 mb-6">
          {error}
        </div>
      )}

      {bots.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-12 text-center">
          <Bot className="mx-auto h-12 w-12 text-[var(--muted-foreground)]/50" />
          <h2 className="mt-4 text-lg font-medium text-[var(--foreground)]">No TutorBots yet</h2>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            Create your first TutorBot to get started with personalized AI tutoring.
          </p>
          <Link
            href="/tutorbot/boarding"
            className="inline-flex items-center gap-2 mt-6 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 transition-opacity"
          >
            <Plus className="h-4 w-4" />
            Create Your First TutorBot
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {bots.map(bot => (
            <BotCard key={bot.bot_id} bot={bot} onStop={stopBot} />
          ))}
        </div>
      )}
    </div>
  );
}
