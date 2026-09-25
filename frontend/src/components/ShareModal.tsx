"use client";

import { useCallback, useEffect, useState } from "react";

import ConfirmDialog from "@/components/ConfirmDialog";
import { api } from "@/lib/api";
import type { Project, Subscriber } from "@/lib/types";

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
  const [confirming, setConfirming] = useState(false);
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
    setConfirming(false);
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
      <ConfirmDialog
        open={confirming}
        title={`Regenerate the ${label.toLowerCase()}?`}
        message="The current link stops working for everyone who has it, and anyone getting this board's reminders through it stops getting them. You'll need to share the new link again."
        confirmLabel="Regenerate link"
        onConfirm={regenerate}
        onCancel={() => setConfirming(false)}
      />
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
          className="shrink-0 rounded-lg bg-ink px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-ink-700"
        >
          {copied ? "Copied" : "Copy"}
        </button>
        {onRegenerate && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={regenerating}
            aria-label={`Regenerate ${label.toLowerCase()}`}
            title={`Regenerate ${label.toLowerCase()}`}
            className="flex shrink-0 items-center justify-center rounded-lg border border-slate-300 px-2.5 text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg
              viewBox="0 0 20 20"
              fill="currentColor"
              className={`h-4 w-4 ${regenerating ? "animate-spin" : ""}`}
            >
              <path
                fillRule="evenodd"
                d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h1.21a.75.75 0 000-1.5H2.812a.75.75 0 00-.75.75v3.5a.75.75 0 001.5 0v-1.434l.281.282a7 7 0 0011.712-3.138.75.75 0 00-1.443-.395zm1.183-5.93a.75.75 0 00-.75.75v1.434l-.281-.282A7 7 0 003.752 10.534a.75.75 0 101.444.395 5.5 5.5 0 019.201-2.466l.312.311h-1.21a.75.75 0 000 1.5h3.397a.75.75 0 00.75-.75v-3.5a.75.75 0 00-.75-.75z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        )}
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

  // The owner sees who asked for this board's reminders (from "Remind me" on the board).
  const [subscribers, setSubscribers] = useState<Subscriber[] | null>(null);
  const [subscriberError, setSubscriberError] = useState<string | null>(null);
  const projectId = project?.id ?? null;
  const loadSubscribers = useCallback(() => {
    if (projectId === null || !isOwner) return;
    api
      .listSubscribers(projectId)
      .then(setSubscribers)
      .catch(() => setSubscribers([]));
  }, [projectId, isOwner]);
  useEffect(() => {
    setSubscribers(null);
    setSubscriberError(null);
    loadSubscribers();
  }, [loadSubscribers]);

  if (!project) return null;

  // Regenerating a link also ends the reminders of people who joined through it.
  const regenerate = async (which: "view" | "edit") => {
    await onRegenerate(which);
    loadSubscribers();
  };
  const removeSubscriber = async (userId: number) => {
    setSubscriberError(null);
    try {
      await api.removeSubscriber(project.id, userId);
      setSubscribers((cur) => (cur ? cur.filter((s) => s.user_id !== userId) : cur));
    } catch {
      setSubscriberError("Couldn't remove them. Please try again.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onMouseDown={onClose}>
      {/* The dim + blur lives in its own sibling layer, NOT as an ancestor of the panel.
          When backdrop-filter wraps the interactive content, hovering a button forces
          Chrome to re-evaluate the filter and flashes for a frame. Isolating it here
          means button repaints never touch the blurred layer. */}
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" aria-hidden="true" />
      <div
        className="relative w-full max-w-md animate-fade-in rounded-2xl bg-white p-6 shadow-xl"
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
              onRegenerate={isOwner ? () => regenerate("edit") : undefined}
            />
          )}
          <LinkRow
            label="View link"
            hint="read-only"
            token={project.view_token}
            accent="bg-slate-400"
            onRegenerate={isOwner ? () => regenerate("view") : undefined}
          />
        </div>

        <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {isOwner
            ? "Sharing a link grants access to anyone who has it. Regenerate a link to revoke the old one."
            : "These links can't be revoked from here — share them only with people you trust."}
        </p>

        {isOwner && subscribers !== null && (
          <div className="mt-5 border-t border-slate-100 pt-4">
            <h3 className="text-sm font-medium text-slate-700">Reminder emails</h3>
            {subscribers.length === 0 ? (
              <p className="mt-1 text-xs text-slate-500">
                Only you get this board&apos;s reminders. People you share it with can turn them on from the board
                with &ldquo;Remind me&rdquo; once they sign in.
              </p>
            ) : (
              <>
                <p className="mt-1 text-xs text-slate-500">These people also get this board&apos;s deadline reminders.</p>
                <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
                  {subscribers.map((s) => (
                    <li key={s.user_id} className="flex items-center gap-2 px-3 py-2 text-sm">
                      <span className="min-w-0 flex-1 truncate text-slate-700" title={s.email}>
                        {s.email}
                      </span>
                      <span className="shrink-0 text-xs text-slate-400">via {s.via} link</span>
                      <button
                        type="button"
                        onClick={() => removeSubscriber(s.user_id)}
                        aria-label={`Stop reminders for ${s.email}`}
                        className="shrink-0 rounded-md px-2 py-0.5 text-xs font-medium text-slate-500 transition hover:bg-rose-50 hover:text-rose-600"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {subscriberError && <p className="mt-1 text-xs text-red-600">{subscriberError}</p>}
          </div>
        )}

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
