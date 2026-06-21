"use client";

import { useState } from "react";

interface Props {
  onSubmitText: (title: string, transcriptText: string) => Promise<void>;
  onSubmitAudio: (title: string, file: File) => Promise<void>;
}

type Mode = "text" | "audio";

export default function TranscriptUpload({ onSubmitText, onSubmitAudio }: Props) {
  const [mode, setMode] = useState<Mode>("text");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "text" && !text.trim()) return;
    if (mode === "audio" && !file) return;

    setSubmitting(true);
    setError(null);
    try {
      if (mode === "text") {
        await onSubmitText(title, text);
      } else if (file) {
        await onSubmitAudio(title, file);
      }
      setTitle("");
      setText("");
      setFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process transcript");
    } finally {
      setSubmitting(false);
    }
  };

  const segBtn = (m: Mode) =>
    `flex-1 whitespace-nowrap rounded-lg px-3 py-2 font-display text-sm font-semibold transition ${
      mode === m ? "bg-white text-ink shadow-sm" : "text-slate-300 hover:text-white"
    }`;

  return (
    <form
      onSubmit={handleSubmit}
      className="relative overflow-hidden rounded-2xl bg-ink p-6 text-slate-100 shadow-ink"
    >
      {/* Concentric arc motif — the geometric signature, kept quiet in the corner. */}
      <span className="pointer-events-none absolute -right-12 -top-12 h-36 w-36 rounded-full border border-white/15" />
      <span className="pointer-events-none absolute -right-5 -top-5 h-24 w-24 rounded-full border border-white/10" />
      {/* Soft brand wash for depth. */}
      <span
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(440px 220px at 112% -12%, rgba(37,99,217,.22) 0%, transparent 62%)",
        }}
      />

      <div className="relative">
        <div className="mb-3">
          <h2 className="flex items-center gap-2 font-display text-lg font-bold text-white">
            <svg viewBox="0 0 24 24" className="h-4 w-4 text-brand-100" fill="currentColor">
              <path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2z" />
            </svg>
            New meeting
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            AI extracts decisions, action items, owners &amp; deadlines.
          </p>
        </div>

        <div className="mb-3 flex rounded-xl border border-white/10 bg-white/5 p-1">
          <button type="button" className={segBtn("text")} onClick={() => setMode("text")}>
            Paste text
          </button>
          <button type="button" className={segBtn("audio")} onClick={() => setMode("audio")}>
            Audio / video
          </button>
        </div>

        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Meeting title (optional)"
          className="mb-3 w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition focus:border-brand focus:bg-white/10 focus:ring-2 focus:ring-brand/30"
        />

        {mode === "text" ? (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste the raw meeting transcript here — messy is fine."
            rows={6}
            className="w-full resize-y rounded-xl border border-white/15 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition focus:border-brand focus:bg-white/10 focus:ring-2 focus:ring-brand/30"
          />
        ) : (
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-white/20 bg-white/5 px-4 py-8 text-center transition hover:border-white/40 hover:bg-white/10">
            <svg viewBox="0 0 24 24" className="h-7 w-7 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 0L8 8m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
            <span className="text-sm font-medium text-slate-200">
              {file ? file.name : "Click to choose an audio or video file"}
            </span>
            <span className="text-xs text-slate-400">
              Transcribed with Whisper before parsing. Large files may take a minute.
            </span>
            <input
              type="file"
              accept="audio/*,video/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="hidden"
            />
          </label>
        )}

        {error && (
          <p className="mt-3 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="group mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-b from-ink-700 to-ink px-4 py-2.5 font-display text-sm font-semibold text-white shadow-brand ring-1 ring-brand/40 transition hover:brightness-110 disabled:opacity-50"
        >
          {submitting ? (
            <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
          ) : (
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4 text-brand-100 transition-transform group-hover:scale-110"
              fill="currentColor"
            >
              <path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2z" />
            </svg>
          )}
          {submitting
            ? mode === "audio"
              ? "Transcribing & parsing..."
              : "Parsing..."
            : mode === "audio"
              ? "Transcribe & parse"
              : "Parse transcript"}
        </button>
      </div>
    </form>
  );
}
