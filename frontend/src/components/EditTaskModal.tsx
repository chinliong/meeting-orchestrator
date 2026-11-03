"use client";

import { Fragment, useEffect, useRef, useState } from "react";

import AttachmentList from "@/components/AttachmentList";
import SubtaskList from "@/components/SubtaskList";
import { formatMeetingDate, isLowConfidence } from "@/lib/format";
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
  /** A change saved as the card closed failed; the card is gone, so the page shows the message. */
  onSaveErrorAfterClose?: (message: string) => void;
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
  onSaveErrorAfterClose,
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
  // Set once the card is closing, so a save that fails afterwards is reported to the page.
  const closingRef = useRef(false);

  // Seed the fields when the card opens, switches task, or an undo lands (syncNonce). Crucially
  // this does NOT depend on the whole `task` object, so a field auto-save (which replaces the
  // task object) won't re-seed mid-edit and clobber what's being typed elsewhere.
  useEffect(() => {
    if (open) {
      closingRef.current = false;
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

  // The source meeting's date, as the task card shows it, unless the title already has it.
  const formattedMeetingDate = task?.meeting_date ? formatMeetingDate(task.meeting_date) : null;
  const meetingDate =
    formattedMeetingDate !== null && !task?.meeting_title?.includes(formattedMeetingDate)
      ? formattedMeetingDate
      : null;

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
    const previous = savedRef.current[field];
    savedRef.current = { ...savedRef.current, [field]: value };
    try {
      setAutoSaveError(null);
      await onSave(task.id, { [field]: value });
    } catch (err) {
      // Not saved after all: forget it was, so the next blur or closing the card tries again
      // (unless a newer value has been saved for the field since).
      if (savedRef.current[field] === value) savedRef.current = { ...savedRef.current, [field]: previous };
      const message = err instanceof Error ? err.message : "Failed to save changes";
      // A save started by closing the card fails after the card has gone, so tell the page.
      if (closingRef.current) onSaveErrorAfterClose?.(`A change to \u201c${task.description}\u201d wasn\u2019t saved. ${message}`);
      else setAutoSaveError(message);
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
    closingRef.current = true;
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

        <h2 className="pr-16 font-display text-lg font-bold tracking-tight text-slate-900">
          {createMode ? "Add task" : readOnly ? "Task" : "Edit task"}
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          {createMode
            ? "Track something that wasn't captured in a meeting."
            : readOnly
              ? "You're viewing a shared board, so this is read-only."
              : "Edits save automatically as you go."}
        </p>

        {/* Where the task came from, read before checking the fields against it: its meeting,
            the extraction score and the decision behind it. Manual tasks have none, so no block. */}
        {task && (task.source_decision || task.meeting_id !== null) && (
          <div className="mt-4 rounded-lg bg-slate-50 px-3.5 py-3 ring-1 ring-slate-200/70">
            {task.meeting_id !== null && (
              <div className="flex items-start justify-between gap-3 text-xs leading-5 text-slate-500">
                {/* The title wraps rather than truncates; the date never splits across lines. */}
                <span className="min-w-0">
                  From <span className="font-medium text-slate-600">{task.meeting_title}</span>
                  {meetingDate && <span className="whitespace-nowrap"> · {meetingDate}</span>}
                </span>
                {/* Only the parser scores tasks; assistant-created tasks have no score. */}
                {/* Amber below the review threshold, matching the card's "Check this" flag. */}
                {task.confidence !== null &&
                  (isLowConfidence(task.confidence) ? (
                    <span
                      className="inline-flex shrink-0 cursor-help items-center gap-1.5 rounded-full bg-amber-50 px-2 py-0.5 font-medium tabular-nums text-amber-700 ring-1 ring-amber-200"
                      title="The AI was unsure about this one. Check the owner and deadline before relying on it."
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
                      {Math.round(task.confidence * 100)}% · Check this
                    </span>
                  ) : (
                    <span
                      className="shrink-0 cursor-help rounded-full bg-white px-2 py-0.5 font-medium tabular-nums text-slate-600 ring-1 ring-slate-200"
                      title="How explicitly the meeting stated this item, as rated by the AI. It is not a probability that the task is correct."
                    >
                      {Math.round(task.confidence * 100)}% confidence
                    </span>
                  ))}
              </div>
            )}
            {/* Not in quotation marks: the parser may paraphrase. */}
            {task.source_decision ? (
              <SourceText
                key={task.id}
                text={task.source_decision}
                className={task.meeting_id !== null ? "mt-1.5" : ""}
              />
            ) : (
              // The parser leaves this empty when the meeting doesn't make the origin clear. Said
              // plainly so the box isn't half-empty; it is not a review flag (that is the score's job).
              <p className="mt-1.5 text-sm text-slate-400">No source decision was recorded for this task.</p>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="mb-1 block font-display text-sm font-semibold text-slate-700">Description</label>
            <textarea
              autoFocus={!readOnly}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onBlur={task ? handleDescriptionBlur : undefined}
              disabled={readOnly}
              rows={3}
              placeholder={createMode ? "What needs to be done?" : undefined}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:bg-slate-50 disabled:text-slate-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block font-display text-sm font-semibold text-slate-700">Owner</label>
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                onBlur={task ? () => commitField("owner", owner.trim() || null) : undefined}
                disabled={readOnly}
                placeholder="Unassigned"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:bg-slate-50 disabled:text-slate-500"
              />
            </div>
            <div>
              <label className="mb-1 block font-display text-sm font-semibold text-slate-700">Deadline</label>
              <input
                type="date"
                ref={deadlineRef}
                defaultValue={task?.deadline ?? ""}
                onBlur={task ? () => commitField("deadline", deadlineRef.current?.value || null) : undefined}
                disabled={readOnly}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:bg-slate-50 disabled:text-slate-500"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block font-display text-sm font-semibold text-slate-700">Status</label>
            <select
              value={status}
              onChange={(e) => handleStatusChange(e.target.value as TaskStatus)}
              disabled={readOnly}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:bg-slate-50 disabled:text-slate-500"
            >
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {error &&<p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
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
                className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700 disabled:opacity-50"
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

// "Aisha:", "Daniel Tan:" or a recording's "Speaker 1:" opening a line of a quoted exchange.
const SPEAKER = /^([A-Z][\w.'-]*(?: [A-Z0-9][\w.'-]*){0,2}):\s/;

/**
 * The task's source text, folded to three lines when longer. The assistant quotes whole
 * exchanges, which would otherwise push the editable fields down; the first lines already say
 * who committed to what. Speaker names are bold so a multi-turn quote reads as dialogue.
 */
function SourceText({ text, className }: { text: string; className: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  // Measured while folded, so "Show more" appears only when something is actually hidden.
  useEffect(() => {
    const el = ref.current;
    if (el && !expanded) setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [text, expanded]);

  return (
    <div className={className}>
      <p
        ref={ref}
        className={`whitespace-pre-line text-sm leading-relaxed text-slate-700 ${expanded ? "" : "line-clamp-3"}`}
      >
        {text.split("\n").map((line, i) => {
          const speaker = line.match(SPEAKER);
          return (
            <Fragment key={i}>
              {i > 0 && "\n"}
              {speaker ? (
                <>
                  <span className="font-semibold text-slate-800">{speaker[1]}:</span>
                  {line.slice(speaker[1].length + 1)}
                </>
              ) : (
                line
              )}
            </Fragment>
          );
        })}
      </p>
      {overflows && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-1 text-xs font-medium text-slate-500 hover:text-brand"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
