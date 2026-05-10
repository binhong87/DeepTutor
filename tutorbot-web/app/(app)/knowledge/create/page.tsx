"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Upload, Loader2, FileText, X } from "lucide-react";
import { createKnowledgeBase } from "@/lib/knowledge-api";

export default function CreateKnowledgePage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);

  function handleFiles(selected: FileList | null) {
    if (!selected) return;
    setFiles(prev => [...prev, ...Array.from(selected)]);
  }

  function removeFile(index: number) {
    setFiles(prev => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError("");
    setSubmitting(true);
    try {
      const result = await createKnowledgeBase(name.trim(), files);
      // Navigate to list; progress is tracked in background
      router.push("/knowledge");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create knowledge base");
      setSubmitting(false);
    }
  }

  function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <Link href="/knowledge" className="inline-flex items-center gap-1 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] mb-6">
        <ArrowLeft className="h-4 w-4" />
        Back
      </Link>

      <h1 className="text-2xl font-semibold text-[var(--foreground)] mb-8">Create Knowledge Base</h1>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400 mb-6">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm font-medium text-[var(--foreground)] mb-1">Name</label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            placeholder="e.g. Course Materials"
          />
        </div>

        {/* Drop zone */}
        <div
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
          className={`rounded-xl border border-dashed p-8 text-center transition-colors ${
            dragOver
              ? "border-[var(--primary)] bg-[var(--primary)]/5"
              : "border-[var(--border)]"
          }`}
        >
          <Upload className="mx-auto h-8 w-8 text-[var(--muted-foreground)]/50" />
          <p className="mt-2 text-sm text-[var(--muted-foreground)]">Drag and drop files here, or click to browse</p>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">PDF, DOCX, XLSX, PPTX, Markdown, and text files supported</p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={e => handleFiles(e.target.files)}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="inline-block mt-4 cursor-pointer rounded-lg border border-[var(--border)] px-4 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
          >
            Browse Files
          </button>
        </div>

        {/* File list */}
        {files.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-[var(--foreground)]">{files.length} file{files.length !== 1 ? "s" : ""} selected</p>
            <div className="rounded-lg border border-[var(--border)] divide-y divide-[var(--border)]">
              {files.map((file, i) => (
                <div key={`${file.name}-${i}`} className="flex items-center gap-3 px-4 py-2.5">
                  <FileText className="h-4 w-4 text-[var(--muted-foreground)] shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[var(--foreground)] truncate">{file.name}</p>
                    <p className="text-xs text-[var(--muted-foreground)]">{formatSize(file.size)}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="p-1 rounded text-[var(--muted-foreground)] hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950 transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={!name.trim() || submitting}
          className="w-full rounded-lg bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50 transition-opacity inline-flex items-center justify-center gap-2"
        >
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Creating...
            </>
          ) : (
            "Create Knowledge Base"
          )}
        </button>
      </form>
    </div>
  );
}
