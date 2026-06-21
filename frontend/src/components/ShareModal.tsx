"use client";

import { useEffect, useState } from "react";

import type { Project } from "@/lib/types";

interface Props {
  project: Project | null;
  onClose: () => void;
}

function linkFor(token: string): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/?w=${token}`;
}

function LinkRow({ label, hint, token, accent }: { label: string; hint: string; token: string; accent: string }) {
  const [copied, setCopied] = useState(false);
  const url = linkFor(token);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — the field is selectable as a fallback */
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${accent}`} />
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <span className="text-xs text-slate-400">{hint}</span>
      </div>
      <div className="flex gap-2">
        <input
          readOnly
          value={url}
          onFocus={(e) => e.target.select()}
          className="w-full truncate rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-600 outline-none"
        />
        <button
          onClick={copy}
          className="shrink-0 rounded-lg bg-ink px-3 py-2 text-xs font-medium text-white transition hover:bg-ink-700"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export default function ShareModal({ project, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (project) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [project, onClose]);

  if (!project) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-md animate-fade-in rounded-2xl bg-white p-6 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className="font-display text-lg font-bold tracking-tight text-slate-900">Share “{project.name}”</h2>
        <p className="mt-1 text-sm text-slate-500">
          Anyone with a link can open this board — no account needed.
        </p>

        <div className="mt-5 space-y-4">
          {project.edit_token && (
            <LinkRow
              label="Edit link"
              hint="can view & modify"
              token={project.edit_token}
              accent="bg-emerald-500"
            />
          )}
          <LinkRow label="View link" hint="read-only" token={project.view_token} accent="bg-slate-400" />
        </div>

        <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
          These links are permanent and can&apos;t be revoked — share them only with people you trust.
        </p>

        <div className="mt-5 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
