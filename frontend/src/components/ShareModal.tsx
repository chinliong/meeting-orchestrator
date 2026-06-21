"use client";

import { useEffect, useState } from "react";

import type { Project } from "@/lib/types";

interface Props {
  project: Project | null;
  /** Only the signed-in board owner may regenerate links. */
  isOwner: boolean;
  onRegenerate: (which: "view" | "edit") => Promise<void>;
  onClose: () => void;
}

function linkFor(token: string): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/?w=${token}`;
}

function LinkRow({
  label,
  hint,
  token,
  accent,
  onRegenerate,
}: {
  label: string;
  hint: string;
  token: string;
  accent: string;
  /** When present, shows a "Regenerate" action that rotates this link's token. */
  onRegenerate?: () => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  const regenerate = async () => {
    if (!onRegenerate) return;
    if (
      !window.confirm(
        `Regenerate the ${label.toLowerCase()}? The current link will stop working for everyone and you'll need to reshare the new one.`,
      )
    )
      return;
    setRegenerating(true);
    setError(null);
    try {
      await onRegenerate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't regenerate the link");
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${accent}`} />
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <span className="text-xs text-slate-400">{hint}</span>
        {onRegenerate && (
          <button
            type="button"
            onClick={regenerate}
            disabled={regenerating}
            className="ml-auto text-xs font-medium text-slate-500 underline-offset-2 transition hover:text-ink hover:underline disabled:opacity-50"
          >
            {regenerating ? "Regenerating…" : "Regenerate"}
          </button>
        )}
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
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

export default function ShareModal({ project, isOwner, onRegenerate, onClose }: Props) {
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
              onRegenerate={isOwner ? () => onRegenerate("edit") : undefined}
            />
          )}
          <LinkRow
            label="View link"
            hint="read-only"
            token={project.view_token}
            accent="bg-slate-400"
            onRegenerate={isOwner ? () => onRegenerate("view") : undefined}
          />
        </div>

        <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {isOwner
            ? "Sharing a link grants access to anyone who has it. Regenerate a link to revoke the old one."
            : "These links can't be revoked from here — share them only with people you trust."}
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
