"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Bot, Check, Sparkles, BookOpen, Cpu, Loader2, MessageCircle } from "lucide-react";
import { useTutorBots } from "@/context/TutorBotContext";
import type { Soul } from "@/lib/tutorbot-api";

const STEPS = [
  { label: "Welcome", icon: Sparkles },
  { label: "Choose Soul", icon: BookOpen },
  { label: "Name & Describe", icon: Bot },
  { label: "Model", icon: Cpu },
  { label: "Done", icon: Check },
];

export default function BoardingPage() {
  const router = useRouter();
  const { souls, createAndStart } = useTutorBots();

  const [step, setStep] = useState(0);
  const [selectedSoul, setSelectedSoul] = useState<Soul | null>(null);
  const [botId, setBotId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdBotId, setCreatedBotId] = useState<string | null>(null);
  const [error, setError] = useState("");

  function canNext(): boolean {
    switch (step) {
      case 0: return true;
      case 1: return selectedSoul !== null;
      case 2: return botId.trim().length > 0 && name.trim().length > 0;
      case 3: return true;
      default: return true;
    }
  }

  async function handleCreate() {
    setError("");
    setCreating(true);
    const bot = await createAndStart({
      bot_id: botId.trim(),
      name: name.trim(),
      description: description.trim(),
      persona: selectedSoul?.content ?? "",
    });
    setCreating(false);

    if (bot) {
      setCreatedBotId(bot.bot_id);
      setStep(4);
    } else {
      setError("Failed to create bot. Please try again.");
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      {/* Stepper */}
      <div className="flex items-center justify-center gap-1 mb-10">
        {STEPS.map((s, i) => (
          <div key={s.label} className="flex items-center gap-1">
            <div
              className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                i === step
                  ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : i < step
                    ? "bg-[var(--primary)]/15 text-[var(--primary)]"
                    : "bg-[var(--muted)] text-[var(--muted-foreground)]"
              }`}
            >
              <s.icon className="h-3 w-3" />
              <span className="hidden sm:inline">{s.label}</span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`h-px w-4 ${i < step ? "bg-[var(--primary)]/40" : "bg-[var(--border)]"}`} />
            )}
          </div>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400 mb-6">
          {error}
        </div>
      )}

      {/* Step 0: Welcome */}
      {step === 0 && (
        <div className="text-center space-y-6">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--primary)]/10">
            <Sparkles className="h-8 w-8 text-[var(--primary)]" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-[var(--foreground)]">Create Your First TutorBot</h1>
            <p className="mt-2 text-sm text-[var(--muted-foreground)] max-w-md mx-auto">
              TutorBots are AI teaching agents powered by customizable personas, channel integrations, and RAG-powered knowledge bases.
            </p>
          </div>
          <div className="grid gap-3 text-left max-w-sm mx-auto">
            {[
              "Choose a teaching persona from our soul library",
              "Give your bot a unique ID and description",
              "Optionally select an LLM model or use the default",
              "Chat, manage channels, and upload knowledge",
            ].map((text, i) => (
              <div key={i} className="flex items-start gap-2 text-sm text-[var(--muted-foreground)]">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--primary)]/10 text-[var(--primary)] text-xs font-medium mt-0.5">
                  {i + 1}
                </span>
                {text}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Step 1: Choose Soul */}
      {step === 1 && (
        <div>
          <h2 className="text-lg font-semibold text-[var(--foreground)] mb-1">Choose a Soul</h2>
          <p className="text-sm text-[var(--muted-foreground)] mb-6">Pick a teaching persona or use the default.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {souls.map(soul => (
              <button
                key={soul.id}
                onClick={() => setSelectedSoul(soul)}
                className={`text-left rounded-xl border p-4 transition-all ${
                  selectedSoul?.id === soul.id
                    ? "border-[var(--primary)] ring-1 ring-[var(--primary)] bg-[var(--primary)]/5"
                    : "border-[var(--border)] hover:border-[var(--primary)]/50"
                }`}
              >
                <div className="font-medium text-sm text-[var(--foreground)]">{soul.name}</div>
                <div className="text-xs text-[var(--muted-foreground)] mt-0.5 line-clamp-2">{soul.content.slice(0, 120)}</div>
              </button>
            ))}
            <button
              onClick={() => setSelectedSoul({ id: "_none", name: "No Persona", content: "" })}
              className={`text-left rounded-xl border p-4 transition-all ${
                selectedSoul?.id === "_none"
                  ? "border-[var(--primary)] ring-1 ring-[var(--primary)] bg-[var(--primary)]/5"
                  : "border-[var(--border)] hover:border-[var(--primary)]/50"
              }`}
            >
              <div className="font-medium text-sm text-[var(--foreground)]">Start Fresh</div>
              <div className="text-xs text-[var(--muted-foreground)] mt-0.5">No preset persona — define everything later.</div>
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Name & Describe */}
      {step === 2 && (
        <div className="max-w-md mx-auto space-y-5">
          <h2 className="text-lg font-semibold text-[var(--foreground)] mb-1">Name Your Bot</h2>
          <p className="text-sm text-[var(--muted-foreground)] mb-6">
            Choose a unique ID and a display name. The ID becomes part of your bot&apos;s URL.
          </p>
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">Bot ID</label>
            <input
              type="text"
              value={botId}
              onChange={e => setBotId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
              placeholder="my-math-tutor"
            />
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">Only lowercase letters, numbers, hyphens, and underscores.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">Display Name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
              placeholder="My Math Tutor"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--foreground)] mb-1">Description (optional)</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] resize-none"
              placeholder="A helpful math tutor that explains concepts step by step..."
            />
          </div>
        </div>
      )}

      {/* Step 3: Model (optional) */}
      {step === 3 && (
        <div className="text-center space-y-6">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--primary)]/10">
            <Cpu className="h-8 w-8 text-[var(--primary)]" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[var(--foreground)]">Ready to Create</h2>
            <p className="mt-2 text-sm text-[var(--muted-foreground)] max-w-sm mx-auto">
              Your bot will use the default LLM model. You can change this later in settings.
            </p>
          </div>
          <div className="inline-flex flex-wrap items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--muted)]/50 px-5 py-3 text-sm">
            <span className="text-[var(--muted-foreground)]">Soul:</span>
            <span className="font-medium text-[var(--foreground)]">{selectedSoul?.name ?? "None"}</span>
            <span className="text-[var(--border)] hidden sm:inline">|</span>
            <span className="text-[var(--muted-foreground)] hidden sm:inline">ID:</span>
            <span className="font-mono font-medium text-[var(--foreground)] hidden sm:inline">{botId}</span>
            <span className="text-[var(--border)] hidden sm:inline">|</span>
            <span className="text-[var(--muted-foreground)] hidden sm:inline">Name:</span>
            <span className="font-medium text-[var(--foreground)] hidden sm:inline">{name}</span>
          </div>
        </div>
      )}

      {/* Step 4: Done */}
      {step === 4 && (
        <div className="text-center space-y-6">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-green-100 dark:bg-green-900/30">
            <Check className="h-8 w-8 text-green-600 dark:text-green-400" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-[var(--foreground)]">Bot Created!</h1>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">
              {createdBotId && (
                <span className="font-mono text-[var(--foreground)]">{createdBotId}</span>
              )}{" "}
              is now running and ready to chat.
            </p>
          </div>
          <div className="flex items-center justify-center gap-3">
            <Link
              href={`/tutorbot/${createdBotId}/chat`}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-5 py-2.5 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 transition-opacity"
            >
              <MessageCircle className="h-4 w-4" />
              Start Chatting
            </Link>
            <Link
              href="/tutorbot/dashboard"
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-5 py-2.5 text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
            >
              Back to Dashboard
            </Link>
          </div>
        </div>
      )}

      {/* Navigation */}
      {step < 3 && (
        <div className="flex items-center justify-between mt-10 pt-6 border-t border-[var(--border)]">
          <button
            onClick={() => setStep(s => Math.max(0, s - 1))}
            disabled={step === 0}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-30 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <button
            onClick={() => setStep(s => s + 1)}
            disabled={!canNext()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-40 transition-opacity"
          >
            Next
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {step === 3 && (
        <div className="flex items-center justify-between mt-10 pt-6 border-t border-[var(--border)]">
          <button
            onClick={() => setStep(2)}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <button
            onClick={handleCreate}
            disabled={creating}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-5 py-2.5 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {creating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                Create Bot
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
