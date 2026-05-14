"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Copy, Loader2, LogOut } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { useAppShell } from "@/context/AppShellContext";
import { type Theme } from "@/lib/theme";
import { type AppLanguage } from "@/context/app-shell-storage";
import { cn } from "@/lib/utils";

const THEME_OPTIONS: { value: Theme; labelKey: string }[] = [
  { value: "light", labelKey: "Light" },
  { value: "dark", labelKey: "Dark" },
  { value: "glass", labelKey: "Glass" },
  { value: "snow", labelKey: "Snow" },
];

const LANGUAGE_OPTIONS: { value: AppLanguage; labelKey: string }[] = [
  { value: "en", labelKey: "English" },
  { value: "zh", labelKey: "Chinese" },
];

export default function ProfilePage() {
  const router = useRouter();
  const { t } = useTranslation();
  const { status, loading, logout, isAuthenticated } = useAuth();
  const { theme, setTheme, language, setLanguage } = useAppShell();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [loading, isAuthenticated, router]);

  if (loading || !status) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  const username = status.username ?? "?";
  const initial = username.charAt(0).toUpperCase();
  const isAdmin = status.is_admin;
  const userId = status.user_id ?? "";

  async function handleCopy() {
    if (!userId) return;
    try {
      await navigator.clipboard.writeText(userId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable — silently ignore
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <h1 className="text-2xl font-semibold text-[var(--foreground)] mb-8">
        {t("Profile")}
      </h1>

      {/* Identity */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-6 mb-6">
        <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">
          {t("Identity")}
        </h2>
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--primary)]/10 text-lg font-semibold text-[var(--primary)] shrink-0">
            {initial}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-lg font-semibold text-[var(--foreground)] truncate">
                {username}
              </span>
              <span
                className={cn(
                  "inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
                  isAdmin
                    ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
                    : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
                )}
              >
                {isAdmin ? t("Admin") : t("User")}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <span>{t("User ID")}:</span>
              <code className="font-mono text-[var(--foreground)] truncate">{userId}</code>
              <button
                onClick={handleCopy}
                disabled={!userId}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-0.5 text-[11px] hover:bg-[var(--muted)] transition-colors disabled:opacity-50"
              >
                {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                {copied ? t("Copied") : t("Copy")}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Preferences */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-6 mb-6">
        <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">
          {t("Preferences")}
        </h2>
        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-2">
              {t("Language")}
            </label>
            <div className="inline-flex rounded-lg border border-[var(--border)] p-1 bg-[var(--background)]">
              {LANGUAGE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setLanguage(opt.value)}
                  className={cn(
                    "px-3 py-1.5 text-sm rounded-md transition-colors",
                    language === opt.value
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]",
                  )}
                >
                  {t(opt.labelKey)}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-2">
              {t("Theme")}
            </label>
            <div className="inline-flex flex-wrap rounded-lg border border-[var(--border)] p-1 bg-[var(--background)]">
              {THEME_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setTheme(opt.value)}
                  className={cn(
                    "px-3 py-1.5 text-sm rounded-md transition-colors",
                    theme === opt.value
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]",
                  )}
                >
                  {t(opt.labelKey)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Account */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-6">
        <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">
          {t("Account")}
        </h2>
        <button
          onClick={logout}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
        >
          <LogOut className="h-4 w-4" />
          {t("Sign out")}
        </button>
      </section>
    </div>
  );
}
