"use client";

import { useEffect, useState } from "react";

interface Props {
  open: boolean;
  mode: "create" | "edit";
  initialName?: string;
  initialDescription?: string;
  onClose: () => void;
  onSubmit: (name: string, description: string, notifyMuted: boolean) => Promise<void>;
  /** Only a signed-in account can ever receive deadline reminders, so the mute toggle is
   * hidden entirely for guest sessions — there'd be nothing for it to control. */
  showNotifyMute?: boolean;
  initialNotifyMuted?: boolean;
}

export default function ProjectModal({
  open,
  mode,
  initialName = "",
  initialDescription = "",
  onClose,
  onSubmit,
  showNotifyMute = false,
  initialNotifyMuted = false,
}: Props) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const [notifyMuted, setNotifyMuted] = useState(initialNotifyMuted);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed fields from the current values each time the modal opens, and close on Escape.
  useEffect(() => {
    if (open) {
      setName(initialName);
      setDescription(initialDescription);
      setNotifyMuted(initialNotifyMuted);
      setError(null);
    }
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const isEdit = mode === "edit";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(name.trim(), description.trim(), notifyMuted);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save project");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-md animate-fade-in rounded-2xl bg-white p-6 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-900">
          {isEdit ? "Edit project" : "New project"}
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          {isEdit
            ? "Rename this project or update its description."
            : "Group meetings and their action items under a project."}
        </p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">Name</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. SAP S/4HANA Go-Live Programme"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Description <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this workstream is about..."
              rows={3}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            />
          </div>

          {isEdit && showNotifyMute && (
            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={notifyMuted}
                onChange={(e) => setNotifyMuted(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400"
              />
              <span>
                Mute deadline email reminders for this project
                <span className="block text-xs text-slate-400">
                  Your account-wide reminder setting stays on for other projects.
                </span>
              </span>
            </label>
          )}

          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !name.trim()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-50"
            >
              {submitting ? "Saving..." : isEdit ? "Save changes" : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
