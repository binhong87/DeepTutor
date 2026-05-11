"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect } from "react";
import { Bot, LogIn, Sparkles, UserPlus } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";

export default function LandingPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const { isAuthenticated, loading, status } = useAuth();

  useEffect(() => {
    if (loading) return;

    if (status && !status.enabled) {
      router.replace("/tutorbot/dashboard");
      return;
    }

    if (isAuthenticated) {
      router.replace("/tutorbot/dashboard");
      return;
    }
  }, [loading, isAuthenticated, status, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--background)]">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--primary)] border-t-transparent" />
      </div>
    );
  }

  if (isAuthenticated || (status && !status.enabled)) {
    return null;
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--background)] px-6">
      <div className="max-w-lg mx-auto text-center space-y-8">
        <div className="space-y-4">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--primary)]/10">
            <Bot className="h-8 w-8 text-[var(--primary)]" />
          </div>
          <div>
            <h1 className="text-3xl font-semibold text-[var(--foreground)] tracking-tight">
              DeepTutor
            </h1>
            <p className="mt-3 text-[15px] text-[var(--muted-foreground)] leading-relaxed max-w-sm mx-auto">
              {t("landing.subtitle")}
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            href="/register"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-6 py-3 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 transition-opacity shadow-sm"
          >
            <UserPlus className="h-4 w-4" />
            {t("Get Started")}
          </Link>
          <Link
            href="/login"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-6 py-3 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 transition-opacity shadow-sm"
          >
            <LogIn className="h-4 w-4" />
            {t("Sign In")}
          </Link>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-4">
          {[
            { title: t("AI Tutors"), desc: t("ai.tutors.desc") },
            { title: t("Knowledge Bases"), desc: t("kb.desc") },
            { title: t("Multi-User"), desc: t("multi.user.desc") },
          ].map((f) => (
            <div key={f.title} className="text-left space-y-1">
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-[var(--primary)]" />
                <span className="text-sm font-medium text-[var(--foreground)]">{f.title}</span>
              </div>
              <p className="text-xs text-[var(--muted-foreground)] leading-relaxed pl-5">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
