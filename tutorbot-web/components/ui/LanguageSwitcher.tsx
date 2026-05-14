"use client";

import { Languages } from "lucide-react";
import { useAppShell } from "@/context/AppShellContext";
import { cn } from "@/lib/utils";

export default function LanguageSwitcher({ className }: { className?: string }) {
  const { language, setLanguage } = useAppShell();
  const next = language === "zh" ? "en" : "zh";
  const label = language === "zh" ? "EN" : "中";

  return (
    <button
      type="button"
      onClick={() => setLanguage(next)}
      aria-label={language === "zh" ? "Switch to English" : "切换到中文"}
      title={language === "zh" ? "English" : "中文"}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-xs font-medium text-[var(--muted-foreground)] shadow-sm transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]",
        className,
      )}
    >
      <Languages className="h-3.5 w-3.5" />
      <span>{label}</span>
    </button>
  );
}
