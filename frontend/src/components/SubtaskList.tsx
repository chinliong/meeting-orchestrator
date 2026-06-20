"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Subtask, TaskMeta } from "@/lib/types";

interface Props {
  taskId: number;
  canEdit: boolean;
  /** Report the rollup counts up so the task card badge stays in sync. */
  onMetaChange: (meta: Partial<TaskMeta>) => void;
}

export default function SubtaskList({ taskId, canEdit, onMetaChange }: Props) {
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [adding, setAdding] = useState(false);

  // Inline title editing.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");

  // AI "Generate" menu.
  const [menuOpen, setMenuOpen] = useState(false);
  const [instructMode, setInstructMode] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [generating, setGenerating] = useState(false);

  // Keep onMetaChange identity stable for the load effect.
  const onMetaRef = useRef(onMetaChange);
  onMetaRef.current = onMetaChange;

  const sync = (list: Subtask[]) => {
    setSubtasks(list);
    onMetaRef.current({
      subtask_total: list.length,
      subtask_done: list.filter((s) => s.done).length,
    });
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listSubtasks(taskId)
      .then((list) => {
        if (cancelled) return;
        setSubtasks(list);
        onMetaRef.current({
          subtask_total: list.length,
          subtask_done: list.filter((s) => s.done).length,
        });
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const doneCount = subtasks.filter((s) => s.done).length;

  const addSubtask = async () => {
    const title = newTitle.trim();
    if (!title || adding) return;
    setAdding(true);
    setError(null);
    try {
      const created = await api.createSubtask(taskId, title);
      sync([...subtasks, created]);
      setNewTitle("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAdding(false);
    }
  };

  const toggleDone = async (subtask: Subtask) => {
    // Optimistic — flip immediately, reconcile from the server response.
    const next = subtasks.map((s) => (s.id === subtask.id ? { ...s, done: !s.done } : s));
    sync(next);
    try {
      const updated = await api.updateSubtask(subtask.id, { done: !subtask.done });
      sync(subtasks.map((s) => (s.id === updated.id ? updated : s)));
    } catch (err) {
      sync(subtasks); // revert
      setError((err as Error).message);
    }
  };

  const commitTitle = async (subtask: Subtask) => {
    const title = editDraft.trim();
    setEditingId(null);
    if (!title || title === subtask.title) return;
    try {
      const updated = await api.updateSubtask(subtask.id, { title });
      sync(subtasks.map((s) => (s.id === updated.id ? updated : s)));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const removeSubtask = async (id: number) => {
    const prev = subtasks;
    sync(subtasks.filter((s) => s.id !== id));
    try {
      await api.deleteSubtask(id);
    } catch (err) {
      sync(prev);
      setError((err as Error).message);
    }
  };

  const generate = async (withInstructions: boolean) => {
    if (generating) return;
    setMenuOpen(false);
    setGenerating(true);
    setError(null);
    try {
      const created = await api.generateSubtasks(
        taskId,
        withInstructions ? instructions.trim() : undefined
      );
      sync([...subtasks, ...created]);
      setInstructMode(false);
      setInstructions("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-700">Subtasks</span>
          {canEdit && (
            <div className="relative">
              <button
                type="button"
                onClick={() => {
                  setMenuOpen((v) => !v);
                  setInstructMode(false);
                }}
                disabled={generating}
                className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-50"
                title="Generate subtasks with AI"
              >
                {generating ? (
                  <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <SparkleIcon className="h-3.5 w-3.5" />
                )}
                {generating ? "Generating…" : "Generate"}
              </button>

              {menuOpen && (
                <>
                  <button
                    type="button"
                    aria-label="Close menu"
                    onClick={() => setMenuOpen(false)}
                    className="fixed inset-0 z-40 cursor-default"
                  />
                  <div className="absolute left-0 top-full z-50 mt-1 w-56 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
                    <p className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                      Generate
                    </p>
                    <button
                      type="button"
                      onClick={() => generate(false)}
                      className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      <SparkleIcon className="h-4 w-4 text-emerald-600" />
                      From task details
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setInstructMode(true);
                        setMenuOpen(false);
                      }}
                      className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      <span className="flex h-4 w-4 items-center justify-center font-serif text-sm font-semibold text-slate-500">
                        T
                      </span>
                      From your instructions
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
        {subtasks.length > 0 && (
          <span className="text-xs font-medium text-slate-500">
            {doneCount}/{subtasks.length} done
          </span>
        )}
      </div>

      {/* "From your instructions" inline composer */}
      {canEdit && instructMode && (
        <div className="mb-2 flex items-center gap-2">
          <input
            autoFocus
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") generate(true);
              if (e.key === "Escape") setInstructMode(false);
            }}
            placeholder="e.g. focus on testing and rollback steps"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
          />
          <button
            type="button"
            onClick={() => generate(true)}
            disabled={generating || !instructions.trim()}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-50"
          >
            Generate
          </button>
        </div>
      )}

      {error && <p className="mb-2 rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-600">{error}</p>}

      {loading ? (
        <p className="py-2 text-sm text-slate-400">Loading…</p>
      ) : subtasks.length === 0 && !instructMode ? (
        <p className="py-1 text-sm text-slate-400">
          {canEdit ? "No subtasks yet — add one or generate with AI." : "No subtasks."}
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-100">
          {subtasks.map((subtask) => (
            <li key={subtask.id} className="group/sub flex items-center gap-2.5 px-2.5 py-2">
              <button
                type="button"
                onClick={() => canEdit && toggleDone(subtask)}
                disabled={!canEdit}
                aria-label={subtask.done ? "Mark not done" : "Mark done"}
                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition ${
                  subtask.done
                    ? "border-emerald-500 bg-emerald-500 text-white"
                    : "border-slate-300 bg-white text-transparent hover:border-slate-400"
                } ${canEdit ? "cursor-pointer" : "cursor-default"}`}
              >
                <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor">
                  <path d="M16.7 5.3a1 1 0 010 1.4l-7 7a1 1 0 01-1.4 0l-3.3-3.3a1 1 0 011.4-1.4l2.6 2.6 6.3-6.3a1 1 0 011.4 0z" />
                </svg>
              </button>

              {canEdit && editingId === subtask.id ? (
                <input
                  autoFocus
                  value={editDraft}
                  onChange={(e) => setEditDraft(e.target.value)}
                  onBlur={() => commitTitle(subtask)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitTitle(subtask);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                  className="flex-1 rounded border border-slate-300 px-1.5 py-0.5 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-200"
                />
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    if (!canEdit) return;
                    setEditingId(subtask.id);
                    setEditDraft(subtask.title);
                  }}
                  className={`flex-1 text-left text-sm ${
                    subtask.done ? "text-slate-400 line-through" : "text-slate-700"
                  } ${canEdit ? "cursor-text" : "cursor-default"}`}
                >
                  {subtask.title}
                </button>
              )}

              {canEdit && (
                <button
                  type="button"
                  onClick={() => removeSubtask(subtask.id)}
                  aria-label="Delete subtask"
                  className="shrink-0 rounded p-0.5 text-slate-300 opacity-0 transition hover:bg-slate-100 hover:text-rose-500 group-hover/sub:opacity-100 [@media(hover:none)]:opacity-100"
                >
                  <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                    <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                  </svg>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <div className="mt-2 flex items-center gap-2">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addSubtask()}
            placeholder="Add a subtask…"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
          />
          <button
            type="button"
            onClick={addSubtask}
            disabled={adding || !newTitle.trim()}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50 disabled:opacity-50"
          >
            Add
          </button>
        </div>
      )}
    </div>
  );
}

function SparkleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={className} fill="currentColor">
      <path d="M10 1.5l1.6 4.1 4.4 1.4-4.4 1.4L10 12.5 8.4 8.4 4 7l4.4-1.4L10 1.5zM4 13l.8 2 2 .8-2 .8L4 18.6l-.8-2-2-.8 2-.8.8-2z" />
    </svg>
  );
}
