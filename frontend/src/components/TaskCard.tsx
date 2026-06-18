"use client";

import { useState } from "react";

import type { Task } from "@/lib/types";
import { avatarColor, confidenceTone, formatDate, initials, isOverdue } from "@/lib/format";

interface Props {
  task: Task;
  /** Project name, shown only when browsing tasks across all projects. */
  projectName?: string | null;
  onDragStart: (e: React.DragEvent, task: Task) => void;
  onEdit: (task: Task) => void;
  onDelete: (id: number) => void;
  onRenameMeeting: (meetingId: number, title: string) => Promise<void>;
}

export default function TaskCard({
  task,
  projectName,
  onDragStart,
  onEdit,
  onDelete,
  onRenameMeeting,
}: Props) {
  const overdue = task.deadline && task.status !== "done" && isOverdue(task.deadline);

  const [expanded, setExpanded] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);

  const startRename = () => {
    setDraftTitle(task.meeting_title ?? "");
    setRenaming(true);
  };

  const commitRename = async () => {
    const next = draftTitle.trim();
    if (task.meeting_id === null || !next || next === task.meeting_title) {
      setRenaming(false);
      return;
    }
    setSavingTitle(true);
    try {
      await onRenameMeeting(task.meeting_id, next);
      setRenaming(false);
    } finally {
      setSavingTitle(false);
    }
  };

  return (
    <div
      draggable={!renaming}
      onDragStart={(e) => onDragStart(e, task)}
      className="group relative mb-2.5 cursor-grab rounded-lg border border-slate-200 bg-white p-3 shadow-card transition hover:border-slate-300 hover:shadow-card-hover active:cursor-grabbing"
    >
      <div className="absolute right-1.5 top-1.5 flex gap-0.5 opacity-0 transition group-hover:opacity-100">
        <button
          onClick={() => onEdit(task)}
          className="rounded p-0.5 text-slate-300 transition hover:bg-slate-100 hover:text-slate-900"
          aria-label="Edit task"
        >
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
            <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.879.506l-3.012.86a.5.5 0 01-.617-.617l.86-3.012a2 2 0 01.506-.879l8.5-8.5z" />
          </svg>
        </button>
        <button
          onClick={() => onDelete(task.id)}
          className="rounded p-0.5 text-slate-300 transition hover:bg-slate-100 hover:text-rose-500"
          aria-label="Delete task"
        >
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
          </svg>
        </button>
      </div>

      {projectName && (
        <div className="mb-1 flex items-center gap-1 pr-12 text-[11px] font-medium text-slate-500">
          <svg viewBox="0 0 20 20" className="h-3 w-3 shrink-0" fill="currentColor">
            <path d="M3 5a2 2 0 012-2h3.5l1.5 1.5H15a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2V5z" />
          </svg>
          <span className="truncate">{projectName}</span>
        </div>
      )}

      {/* Eyebrow: source meeting (editable) or "Added manually" for hand-created tasks. */}
      {task.meeting_id !== null ? (
        renaming ? (
          <div className="mb-1.5 flex items-center gap-1 pr-1">
            <input
              autoFocus
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitRename();
                if (e.key === "Escape") setRenaming(false);
              }}
              disabled={savingTitle}
              className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-[11px] font-medium text-slate-700 outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-200"
            />
          </div>
        ) : (
          <button
            onClick={startRename}
            title={`From meeting: ${task.meeting_title}\nClick to rename (updates all its tasks)`}
            className="group/title mb-1.5 flex max-w-full items-center gap-1 rounded pr-12 text-[11px] font-medium text-slate-400 transition hover:text-slate-600"
          >
            <svg viewBox="0 0 20 20" className="h-3 w-3 shrink-0" fill="currentColor">
              <path d="M4 4a2 2 0 012-2h5.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm3 5a.75.75 0 000 1.5h6a.75.75 0 000-1.5H7zm0 3a.75.75 0 000 1.5h4a.75.75 0 000-1.5H7z" />
            </svg>
            <span className="truncate">{task.meeting_title}</span>
            <svg
              viewBox="0 0 20 20"
              className="h-3 w-3 shrink-0 opacity-0 transition group-hover/title:opacity-100"
              fill="currentColor"
            >
              <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.879.506l-3.012.86a.5.5 0 01-.617-.617l.86-3.012a2 2 0 01.506-.879l8.5-8.5z" />
            </svg>
          </button>
        )
      ) : (
        <div className="mb-1.5 flex items-center gap-1 pr-12 text-[11px] font-medium text-slate-400">
          <svg viewBox="0 0 20 20" className="h-3 w-3 shrink-0" fill="currentColor">
            <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.879.506l-3.012.86a.5.5 0 01-.617-.617l.86-3.012a2 2 0 01.506-.879l8.5-8.5z" />
          </svg>
          <span className="truncate">Added manually</span>
        </div>
      )}

      <p
        onClick={() => setExpanded((v) => !v)}
        className={`pr-12 text-sm font-medium leading-snug text-slate-800 ${
          expanded ? "" : "line-clamp-3"
        }`}
      >
        {task.description}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {task.owner ? (
          <span className="inline-flex items-center gap-1.5">
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold text-white ${avatarColor(
                task.owner
              )}`}
            >
              {initials(task.owner)}
            </span>
            <span className="text-xs font-medium text-slate-600">{task.owner}</span>
          </span>
        ) : (
          <span className="text-xs italic text-slate-400">Unassigned</span>
        )}

        {task.deadline && (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              overdue ? "bg-rose-50 text-rose-600" : "bg-slate-100 text-slate-600"
            }`}
          >
            <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor">
              <path d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v9a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zM4 7h12v8H4V7z" />
            </svg>
            {formatDate(task.deadline)}
            {overdue && " · overdue"}
          </span>
        )}

        {task.meeting_id !== null && (
          <span
            className={`ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${confidenceTone(
              task.confidence
            )}`}
            title={`AI confidence: ${Math.round(
              task.confidence * 100
            )}% sure this is a real action item. Lower means double-check it.`}
          >
            <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor">
              <path d="M2 12a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1H3a1 1 0 01-1-1v-4zm6-4a1 1 0 011-1h2a1 1 0 011 1v8a1 1 0 01-1 1H9a1 1 0 01-1-1V8zm6-4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
            </svg>
            {Math.round(task.confidence * 100)}% conf.
          </span>
        )}
      </div>
    </div>
  );
}
