"use client";

import { useEffect, useRef, useState } from "react";

import AttachmentList from "@/components/AttachmentList";
import SubtaskList from "@/components/SubtaskList";
import type { Task, TaskMeta, TaskStatus, UndoAction } from "@/lib/types";

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
  /** False on view-only (shared) boards: fields are read-only and nothing is saved. */
  canEdit: boolean;
  /** Whether the global undo stack has anything to undo. */
  canUndo?: boolean;
  /** Bumped by the parent after an undo so the card re-seeds its fields from the reverted task. */
  syncNonce?: number;
  onUndo?: () => void;
  /** Push a reversible action (used so subtask edits land on the same global undo stack). */
  onPushUndo?: (action: UndoAction) => void;
  /** Bumped when an undo touches subtasks, so the open list re-fetches from the server. */
  subtaskReloadNonce?: number;
  onRequestSubtaskReload?: () => void;
  onClose: () => void;
  onSave: (id: number, patch: Partial<TaskValues>) => Promise<void>;
  onCreate: (values: TaskValues) => Promise<void>;
  /** Bubble up subtask/attachment count changes so the task card badges stay in sync. */
  onMetaChange?: (taskId: number, meta: Partial<TaskMeta>) => void;
}

const STATUSES: { value: TaskStatus; label: string }[] = [
  { value: "todo", label: "To Do" },
  { value: "in_progress", label: "In Progress" },
  { value: "done", label: "Done" },
];

export default function EditTaskModal({
  task,
  createMode,
  canEdit,
  canUndo = false,
  syncNonce = 0,
  onUndo,
  onPushUndo,
  subtaskReloadNonce = 0,
  onRequestSubtaskReload,
  onClose,
  onSave,
  onCreate,
  onMetaChange,
}: Props) {
  const open = task !== null || createMode;
  // Viewing an existing task on a board you can't edit: show everything, change nothing.
  const readOnly = task !== null && !canEdit;

  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");
  const [status, setStatus] = useState<TaskStatus>("todo");
  const [saving, setSaving] = useState(false); // create-mode submit
  const [error, setError] = useState<string | null>(null); // create-mode submit error
  const [autoSaveError, setAutoSaveError] = useState<string | null>(null); // edit-mode field save
  // The deadline is uncontrolled: a controlled <input type="date"> reports an incomplete value
  // as "" mid-typing, which would wipe what the user is typing. We read it on blur/submit.
  const deadlineRef = useRef<HTMLInputElement>(null);
  // Last values persisted to the server, so edit-mode blurs only save fields that actually changed.
  const savedRef = useRef<TaskValues>({ description: "", owner: null, deadline: null, status: "todo" });
  // Latest close handler, so the Escape listener can flush pending edits without re-subscribing.
  const closeRef = useRef<() => void>(onClose);

  // Seed the fields when the card opens, switches task, or an undo lands (syncNonce). Crucially
  // this does NOT depend on the whole `task` object, so a field auto-save (which replaces the
  // task object) won't re-seed mid-edit and clobber what's being typed elsewhere.
  useEffect(() => {
    if (open) {
      setDescription(task?.description ?? "");
      setOwner(task?.owner ?? "");
      setStatus(task?.status ?? "todo");
      if (deadlineRef.current) deadlineRef.current.value = task?.deadline ?? ""; // uncontrolled
      setError(null);
      setAutoSaveError(null);
      savedRef.current = {
        description: task?.description ?? "",
        owner: task?.owner ?? null,
        deadline: task?.deadline ?? null,
        status: task?.status ?? "todo",
      };
    }
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, task?.id, syncNonce]);

  if (!open) return null;

  // --- create mode: collect the fields and submit once ---
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!description.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate({
        description: description.trim(),
        owner: owner.trim() || null,
        deadline: deadlineRef.current?.value || null,
        status,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save task");
    } finally {
      setSaving(false);
    }
  };

  // --- edit mode: save a single field the moment it changes, only if it actually changed ---
  const commitField = async <K extends keyof TaskValues>(field: K, value: TaskValues[K]) => {
    if (!task || readOnly || savedRef.current[field] === value) return;
    savedRef.current = { ...savedRef.current, [field]: value };
    try {
      setAutoSaveError(null);
      await onSave(task.id, { [field]: value });
    } catch (err) {
      setAutoSaveError(err instanceof Error ? err.message : "Failed to save changes");
    }
  };

  const handleDescriptionBlur = () => {
    const value = description.trim();
    if (!value) {
      // Never let a task lose its description — restore the last good value.
      setDescription(savedRef.current.description);
      return;
    }
    setDescription(value);
    commitField("description", value);
  };

  const handleStatusChange = (value: TaskStatus) => {
    setStatus(value);
    commitField("status", value);
  };

  // Save any still-pending edits before the modal goes away. Closing (✕ / Escape / click-away)
  // unmounts the inputs before their blur fires, so without this a just-typed change would be
  // lost. commitField skips fields that haven't actually changed, so this is cheap.
  const flushPending = () => {
    if (!task || readOnly) return;
    const trimmedDescription = description.trim();
    if (trimmedDescription) commitField("description", trimmedDescription);
    commitField("owner", owner.trim() || null);
    commitField("deadline", deadlineRef.current?.value || null);
    commitField("status", status);
  };

  const handleClose = () => {
    flushPending();
    onClose();
  };
  closeRef.current = handleClose;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onMouseDown={handleClose}
    >
      <div
        key={task?.id ?? "new"}
        className="relative max-h-[90dvh] w-full max-w-lg animate-fade-in overflow-y-auto rounded-2xl bg-white p-5 shadow-xl sm:p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="absolute right-3 top-3 flex items-center gap-0.5">
          {task && !readOnly && onUndo && (
            <button
              type="button"
              onClick={onUndo}
              disabled={!canUndo}
              aria-label="Undo last change"
              title="Undo last change (⌘Z / Ctrl+Z)"
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
            >
              <svg viewBox="0 0 20 20" className="h-5 w-5" fill="currentColor">
                <path d="M8 5V2.5a.5.5 0 00-.82-.38l-4.5 3.75a.5.5 0 000 .76l4.5 3.75A.5.5 0 008 10V7.5h3.5a4 4 0 110 8H7a1 1 0 100 2h4.5a6 6 0 100-12H8z" />
              </svg>
            </button>
          )}
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <svg viewBox="0 0 20 20" className="h-5 w-5" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        </div>

        <h2 className="pr-16 text-lg font-semibold text-slate-900">
          {createMode ? "Add task" : readOnly ? "Task" : "Edit task"}
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          {createMode
            ? "Track something that wasn't captured in a meeting."
            : readOnly
              ? "You're viewing a shared board, so this is read-only."
              : "Edits save automatically as you go."}
        </p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">Description</label>
            <textarea
              autoFocus={!readOnly}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onBlur={task ? handleDescriptionBlur : undefined}
              disabled={readOnly}
              rows={3}
              placeholder={createMode ? "What needs to be done?" : undefined}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50 disabled:text-slate-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Owner</label>
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                onBlur={task ? () => commitField("owner", owner.trim() || null) : undefined}
                disabled={readOnly}
                placeholder="Unassigned"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50 disabled:text-slate-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Deadline</label>
              <input
                type="date"
                ref={deadlineRef}
                defaultValue={task?.deadline ?? ""}
                onBlur={task ? () => commitField("deadline", deadlineRef.current?.value || null) : undefined}
                disabled={readOnly}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50 disabled:text-slate-500"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">Status</label>
            <select
              value={status}
              onChange={(e) => handleStatusChange(e.target.value as TaskStatus)}
              disabled={readOnly}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50 disabled:text-slate-500"
            >
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
          {autoSaveError && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{autoSaveError}</p>
          )}

          {/* Create needs an explicit submit (there's no task to save into yet). Editing saves
              each field on change, so it has no Save button — just close when done. */}
          {createMode && (
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
                {saving ? "Saving..." : "Add task"}
              </button>
            </div>
          )}
        </form>

        {/* Subtasks & attachments live on an existing task, so they're hidden while creating.
            They also save on their own — the whole card is auto-saved. */}
        {task && (
          <div className="mt-5 space-y-5 border-t border-slate-100 pt-5">
            <SubtaskList
              taskId={task.id}
              canEdit={canEdit}
              reloadNonce={subtaskReloadNonce}
              onMetaChange={(meta) => onMetaChange?.(task.id, meta)}
              pushUndo={onPushUndo}
              requestReload={onRequestSubtaskReload}
            />
            <AttachmentList
              taskId={task.id}
              canEdit={canEdit}
              onMetaChange={(meta) => onMetaChange?.(task.id, meta)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
