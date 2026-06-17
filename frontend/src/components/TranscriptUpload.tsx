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

  const tabClass = (m: Mode) =>
    `rounded px-3 py-1 text-sm font-medium ${
      mode === m ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600"
    }`;

  return (
    <form onSubmit={handleSubmit} className="mb-6 rounded-xl bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">Submit a meeting</h2>
        <div className="flex gap-2">
          <button type="button" className={tabClass("text")} onClick={() => setMode("text")}>
            Paste text
          </button>
          <button type="button" className={tabClass("audio")} onClick={() => setMode("audio")}>
            Upload audio/video
          </button>
        </div>
      </div>

      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Meeting title"
        className="mb-2 w-full rounded border border-gray-300 px-3 py-2 text-sm"
      />

      {mode === "text" ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste raw meeting transcript text here..."
          rows={6}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
        />
      ) : (
        <div className="rounded border border-dashed border-gray-300 px-3 py-4 text-sm">
          <input
            type="file"
            accept="audio/*,video/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
          <p className="mt-2 text-xs text-gray-500">
            Audio/video is transcribed locally with Whisper before parsing. Large files may take a
            while.
          </p>
        </div>
      )}

      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="mt-3 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {submitting
          ? mode === "audio"
            ? "Transcribing & parsing..."
            : "Parsing transcript..."
          : mode === "audio"
            ? "Transcribe & parse"
            : "Parse transcript"}
      </button>
    </form>
  );
}
