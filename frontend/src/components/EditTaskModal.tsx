"use client";

import { useEffect, useState } from "react";

import type { Task, TaskStatus } from "@/lib/types";

interface TaskValues {
  description: string;
  owner: string | null;
  deadline: string | null;
  status: TaskStatus;
}

interface Props {
  /** The task being edited. Null while creating a new one. */
  task: Task | null;
  /** Open the modal in "add a new task" mode (task stays null). */
  createMode: boolean;
  onClose: () => void;
  onSave: (id: number, patch: Partial<TaskValues>) => Promise<void>;
  onCreate: (values: TaskValues) => Promise<void>;
}

const STATUSES: { value: TaskStatus; label: string }[] = [
  { value: "todo", label: "To Do" },
  { value: "in_progress", label: "In Progress" },
  { value: "done", label: "Done" },
];

export default function EditTaskModal({ task, createMode, onClose, onSave, onCreate }: Props) {
  const open = task !== null || createMode;

  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");
  const [deadline, setDeadline] = useState("");
  const [status, setStatus] = useState<TaskStatus>("todo");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDescription(task?.description ?? "");
      setOwner(task?.owner ?? "");
      setDeadline(task?.deadline ?? "");
      setStatus(task?.status ?? "todo");
      setError(null);
    }
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, task, onClose]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!description.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const values: TaskValues = {
        description: description.trim(),
        owner: owner.trim() || null,
        deadline: deadline || null,
        status,
      };
      if (task) {
        await onSave(task.id, values);
      } else {
        await onCreate(values);
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save task");
    } finally {
      setSaving(false);
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
          {createMode ? "Add task" : "Edit task"}
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          {createMode
            ? "Track something that wasn't captured in a meeting."
            : "Correct anything the AI got wrong."}
        </p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">Description</label>
            <textarea
              autoFocus
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder={createMode ? "What needs to be done?" : undefined}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Owner</label>
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="Unassigned"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Deadline</label>
              <input
                type="date"
                value={deadline}
                onChange={(e) => setDeadline(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as TaskStatus)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            >
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

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
              disabled={saving || !description.trim()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-50"
            >
              {saving ? "Saving..." : createMode ? "Add task" : "Save changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
