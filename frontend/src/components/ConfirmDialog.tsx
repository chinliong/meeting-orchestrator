"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";

interface Props {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  /** "danger" for actions that destroy data (a red button); "default" otherwise. */
  tone?: "danger" | "default";
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * An in-app confirmation, used in place of the browser's window.confirm so it matches the rest
 * of the app and can say exactly what will happen. Cancel is focused first, so pressing Enter by
 * reflex does not confirm a destructive action.
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  tone = "default",
  busy = false,
  error,
  onConfirm,
  onCancel,
}: Props) {
  // Escape cancels this dialog only. It listens in the capture phase and stops the event, so a
  // dialog underneath (e.g. Share) does not also close.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      if (!busy) onCancel();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, busy, onCancel]);

  if (!open) return null;

  // Rendered at the top of the page, above any dialog it was opened from. React still bubbles
  // events through the component tree, so mouse-downs are stopped here to keep them from
  // reaching (and closing) that dialog.
  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onMouseDown={(e) => {
        e.stopPropagation();
        if (!busy) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className="w-full max-w-sm animate-fade-in rounded-2xl bg-white p-5 shadow-xl sm:p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-dialog-title" className="font-display text-lg font-bold tracking-tight text-slate-900">
          {title}
        </h2>
        <div className="mt-2 text-sm leading-relaxed text-slate-600">{message}</div>
        {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            autoFocus
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={`rounded-lg px-4 py-2 text-sm font-medium text-white shadow-sm transition disabled:opacity-50 ${
              tone === "danger" ? "bg-rose-600 hover:bg-rose-700" : "bg-ink hover:bg-ink-700"
            }`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
