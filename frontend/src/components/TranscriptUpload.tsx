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
    if (!title.trim()) return;
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
    `flex-1 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition ${
      mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
    }`;

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-slate-200 bg-white p-5 shadow-card">
      <div className="mb-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <svg viewBox="0 0 24 24" className="h-4 w-4 text-slate-900" fill="currentColor">
            <path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2z" />
          </svg>
          New meeting
        </h2>
        <p className="mt-0.5 text-xs text-slate-500">
          AI extracts decisions, action items, owners &amp; deadlines.
        </p>
      </div>

      <div className="mb-3 flex rounded-lg bg-slate-100 p-1">
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
        placeholder="Meeting title"
        className="mb-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
      />

      {mode === "text" ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste the raw meeting transcript here — messy is fine."
          rows={6}
          className="w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
        />
      ) : (
        <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center transition hover:border-slate-400 hover:bg-slate-100">
          <svg viewBox="0 0 24 24" className="h-7 w-7 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 0L8 8m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
          </svg>
          <span className="text-sm font-medium text-slate-700">
            {file ? file.name : "Click to choose an audio or video file"}
          </span>
          <span className="text-xs text-slate-400">
            Transcribed locally with Whisper before parsing.
          </span>
          <input
            type="file"
            accept="audio/*,video/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="hidden"
          />
        </label>
      )}

      {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

      <button
        type="submit"
        disabled={submitting}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-50"
      >
        {submitting && (
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
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
    </form>
  );
}
