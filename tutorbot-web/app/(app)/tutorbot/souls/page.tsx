"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, Loader2 } from "lucide-react";
import { useTutorBots } from "@/context/TutorBotContext";
import { useTranslation } from "react-i18next";

export default function SoulsPage() {
  const { souls, loading } = useTutorBots();
  const [expanded, setExpanded] = useState<string | null>(null);
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <Link href="/tutorbot/dashboard" className="inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] mb-6">
        <ArrowLeft className="h-4 w-4" />
        {t("Dashboard")}
      </Link>

      <h1 className="text-2xl font-semibold text-[var(--foreground)] mb-2">{t("Soul Templates")}</h1>
      <p className="text-sm text-[var(--muted-foreground)] mb-8">
        {t("Reusable personality templates for creating TutorBots. {{count}} available.", { count: souls.length })}
      </p>

      {souls.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-12 text-center">
          <BookOpen className="mx-auto h-12 w-12 text-[var(--muted-foreground)]/50" />
          <p className="mt-4 text-sm text-[var(--muted-foreground)]">{t("No soul templates yet.")}</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {souls.map(soul => (
            <div
              key={soul.id}
              className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-5 hover:shadow-sm transition-shadow cursor-pointer"
              onClick={() => setExpanded(expanded === soul.id ? null : soul.id)}
            >
              <div className="flex items-center gap-3 mb-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--primary)]/10">
                  <BookOpen className="h-5 w-5 text-[var(--primary)]" />
                </div>
                <div>
                  <h3 className="font-medium text-[var(--foreground)]">{soul.name}</h3>
                  <p className="text-xs text-[var(--muted-foreground)] font-mono">{soul.id}</p>
                </div>
              </div>
              {expanded === soul.id && (
                <p className="text-sm text-[var(--muted-foreground)] mt-3 pt-3 border-t border-[var(--border)] whitespace-pre-wrap">
                  {soul.content}
                </p>
              )}
              {expanded !== soul.id && (
                <p className="text-xs text-[var(--muted-foreground)] line-clamp-2 mt-1">{soul.content.slice(0, 150)}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
