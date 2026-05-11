"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save, Trash2, Loader2, AlertTriangle } from "lucide-react";
import { getBot, updateBot, stopBot, destroyBot, type TutorBotDetail } from "@/lib/tutorbot-api";
import { useTranslation } from "react-i18next";

export default function BotSettingsPage() {
  const { botId } = useParams<{ botId: string }>();
  const router = useRouter();
  const { t } = useTranslation();

  const [bot, setBot] = useState<TutorBotDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [confirmDestroy, setConfirmDestroy] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [persona, setPersona] = useState("");

  useEffect(() => {
    let cancelled = false;
    getBot(botId, true)
      .then(b => {
        if (!cancelled) {
          setBot(b);
          setName(b.name);
          setDescription(b.description ?? "");
          setPersona(b.persona ?? "");
          setLoading(false);
        }
      })
      .catch(e => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : t("Failed to load bot"));
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [botId]);

  async function handleSave() {
    setError("");
    setSaving(true);
    try {
      await updateBot(botId, { name, description, persona });
      setSaving(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to save"));
      setSaving(false);
    }
  }

  async function handleStop() {
    try { await stopBot(botId); } catch { /* ignore */ }
  }

  async function handleDestroy() {
    try {
      await destroyBot(botId);
      router.push("/tutorbot/dashboard");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to destroy bot"));
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <Link href="/tutorbot/dashboard" className="inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] mb-6">
        <ArrowLeft className="h-4 w-4" />
        {t("Back to Dashboard")}
      </Link>

      <h1 className="text-2xl font-semibold text-[var(--foreground)] mb-2">{t("Bot Settings")}</h1>
      <p className="text-sm text-[var(--muted-foreground)] mb-8">
        Configure <span className="font-mono text-[var(--foreground)]">{botId}</span>
        {bot && (
          <span className={`ml-2 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
            bot.running
              ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
              : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
          }`}>
            <span className={`h-1.5 w-1.5 rounded-full ${bot.running ? "bg-green-500" : "bg-gray-400"}`} />
            {bot.running ? t("Running") : t("Stopped")}
          </span>
        )}
      </p>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400 mb-6">
          {error}
        </div>
      )}

      {/* Identity */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-6 mb-6">
        <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">{t("Identity")}</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">{t("Display Name")}</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">{t("Description")}</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] resize-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">{t("Persona (Soul)")}</label>
            <textarea
              value={persona}
              onChange={e => setPersona(e.target.value)}
              rows={6}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[var(--ring)] resize-none"
              placeholder={t("You are a helpful tutor...")}
            />
          </div>
        </div>
        <div className="mt-4">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? t("Saving...") : t("Save Changes")}
          </button>
        </div>
      </section>

      {/* Actions */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-6 mb-6">
        <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">{t("Actions")}</h2>
        <div className="flex flex-wrap gap-3">
          {bot?.running && (
            <button
              onClick={handleStop}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
            >
              {t("Stop Bot")}
            </button>
          )}
          <Link
            href={`/tutorbot/${botId}/chat`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
          >
            {t("Open Chat")}
          </Link>
        </div>
      </section>

      {/* Danger Zone */}
      <section className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-950/20 p-6">
        <h2 className="text-sm font-semibold text-red-700 dark:text-red-400 mb-4 flex items-center gap-1.5">
          <AlertTriangle className="h-4 w-4" />
          {t("Danger Zone")}
        </h2>
        <p className="text-sm text-red-600 dark:text-red-400 mb-4">
          {t("Permanently delete this bot and all its data. This action cannot be undone.")}
        </p>
        {!confirmDestroy ? (
          <button
            onClick={() => setConfirmDestroy(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-red-300 dark:border-red-700 px-4 py-2 text-sm font-medium text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-950 transition-colors"
          >
            <Trash2 className="h-4 w-4" />
            {t("Destroy Bot")}
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onClick={handleDestroy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors"
            >
              <Trash2 className="h-4 w-4" />
              {t("Confirm Destroy")}
            </button>
            <button
              onClick={() => setConfirmDestroy(false)}
              className="text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            >
              {t("Cancel")}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
