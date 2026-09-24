"use client";

import { useState } from "react";

import type { Task } from "@/lib/types";
import {
  avatarColor,
  formatDate,
  formatMeetingDate,
  initials,
  isLowConfidence,
  isOverdue,
} from "@/lib/format";

interface Props {
  task: Task;
  /** Project name, shown only when browsing tasks across all projects. */
  projectName?: string | null;
  /** False for view-only (shared) boards: editing affordances are hidden. */
  canEdit: boolean;
  onDragStart: (e: React.DragEvent, task: Task) => void;
  onEdit: (task: Task) => void;
  onDelete: (id: number) => void;
  onRenameMeeting: (meetingId: number, title: string) => Promise<void>;
}

export default function TaskCard({
  task,
  projectName,
  canEdit,
  onDragStart,
  onEdit,
  onDelete,
  onRenameMeeting,
}: Props) {
  const overdue = task.deadline && task.status !== "done" && isOverdue(task.deadline);

  // Shown beside the meeting title so a series of same-named meetings stays distinguishable.
  // Untitled meetings are already named "Meeting · <date>", so the date isn't repeated.
  const meetingDate = task.meeting_date ? formatMeetingDate(task.meeting_date) : null;
  const showMeetingDate = meetingDate !== null && !task.meeting_title?.includes(meetingDate);
  const meetingLabel = showMeetingDate ? `${task.meeting_title} · ${meetingDate}` : task.meeting_title;
  // On the card itself the year is dropped for the current year, leaving room for the title.
  const shortMeetingDate = task.meeting_date ? formatMeetingDate(task.meeting_date, true) : null;

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

  const edgeColor =
    task.status === "done"
      ? "bg-emerald-500"
      : task.status === "in_progress"
        ? "bg-amber-400"
        : "bg-brand";

  return (
    <div
      draggable={canEdit && !renaming}
      onDragStart={(e) => onDragStart(e, task)}
      className={`group relative mb-2 overflow-hidden rounded-xl border border-slate-200/80 bg-white p-3.5 pl-[18px] transition duration-150 hover:border-slate-300 hover:shadow-card-hover ${
        canEdit ? "cursor-grab active:cursor-grabbing" : ""
      }`}
    >
      {/* Status accent edge — quietly colour-codes each card to its column. */}
      <span className={`absolute inset-y-0 left-0 w-1 ${edgeColor}`} aria-hidden />

      <div
        className={`absolute right-1.5 top-1.5 flex gap-0.5 rounded-md bg-white/95 p-0.5 opacity-0 shadow-sm ring-1 ring-slate-200/70 transition group-hover:opacity-100 [@media(hover:none)]:opacity-100 ${
          canEdit ? "" : "hidden"
        }`}
      >
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
        <div className="mb-1 flex items-center gap-1 [@media(hover:none)]:pr-12 text-[11.5px] font-medium text-slate-500">
          <svg viewBox="0 0 20 20" className="h-3 w-3 shrink-0" fill="currentColor">
            <path d="M3 5a2 2 0 012-2h3.5l1.5 1.5H15a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2V5z" />
          </svg>
          <span className="truncate">{projectName}</span>
        </div>
      )}

      {/* Eyebrow: source meeting (editable) or "Added manually" for hand-created tasks. */}
      {task.meeting_id !== null ? (
        !canEdit ? (
          <div
            className="mb-1 flex items-center gap-1 [@media(hover:none)]:pr-12 text-[11.5px] font-medium text-slate-400"
            title={`From meeting: ${meetingLabel}`}
          >
            <span className="truncate">{task.meeting_title}</span>
            {showMeetingDate && <span className="shrink-0">· {shortMeetingDate}</span>}
          </div>
        ) : renaming ? (
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
              className="w-full rounded border border-slate-300 px-1.5 py-0.5 text-xs font-medium text-slate-700 outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-200"
            />
          </div>
        ) : (
          <button
            onClick={startRename}
            title={`From meeting: ${meetingLabel}\nClick to rename (updates all its tasks)`}
            className="group/title mb-1 flex max-w-full items-center gap-1 rounded [@media(hover:none)]:pr-12 text-[11.5px] font-medium text-slate-400 transition hover:text-slate-600"
          >
            <span className="truncate">{task.meeting_title}</span>
            {showMeetingDate && <span className="shrink-0">· {shortMeetingDate}</span>}
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
        <div className="mb-1 flex items-center gap-1 [@media(hover:none)]:pr-12 text-[11.5px] font-medium text-slate-400">
          <svg viewBox="0 0 20 20" className="h-3 w-3 shrink-0" fill="currentColor">
            <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.879.506l-3.012.86a.5.5 0 01-.617-.617l.86-3.012a2 2 0 01.506-.879l8.5-8.5z" />
          </svg>
          <span className="truncate">Added manually</span>
        </div>
      )}

      <p
        onClick={() => setExpanded((v) => !v)}
        className={`text-[14.5px] font-medium leading-snug text-slate-800 ${
          expanded ? "" : "line-clamp-3"
        }`}
      >
        {task.description}
      </p>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {task.owner ? (
          <span className="inline-flex items-center gap-1.5" title="Owner">
            <span
              className={`flex h-[22px] w-[22px] items-center justify-center rounded-full text-[10px] font-semibold ${avatarColor(
                task.owner
              )}`}
            >
              {initials(task.owner)}
            </span>
            <span className="text-[12.5px] font-medium text-slate-700">{task.owner}</span>
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[12.5px] italic text-slate-400">
            <span className="h-[22px] w-[22px] rounded-full border border-dashed border-slate-300" aria-hidden />
            Unassigned
          </span>
        )}

        {task.deadline && (
          <span
            className={`inline-flex items-center gap-1 whitespace-nowrap text-[12.5px] font-medium ${
              overdue ? "text-rose-600" : "text-slate-500"
            }`}
          >
            <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor">
              <path d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v9a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zM4 7h12v8H4V7z" />
            </svg>
            {formatDate(task.deadline)}
            {overdue && " · overdue"}
          </span>
        )}

        {task.subtask_total > 0 && (
          <span
            className={`inline-flex items-center gap-1 whitespace-nowrap text-[12.5px] font-medium ${
              task.subtask_done === task.subtask_total
                ? "text-emerald-600"
                : "text-slate-500"
            }`}
            title={`${task.subtask_done} of ${task.subtask_total} subtasks done`}
          >
            <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor">
              <path d="M3 5.5A1.5 1.5 0 014.5 4h.7l1 1H4.5v9h11V8.8l1.5-1.5v7.2A1.5 1.5 0 0115.5 16h-11A1.5 1.5 0 013 14.5v-9zm14.7-1.2a1 1 0 010 1.4l-7 7a1 1 0 01-1.4 0L6 9.4a1 1 0 011.4-1.4l1.6 1.6 6.3-6.3a1 1 0 011.4 0z" />
            </svg>
            {task.subtask_done}/{task.subtask_total}
          </span>
        )}

        {task.attachment_count > 0 && (
          <span
            className="inline-flex items-center gap-1 whitespace-nowrap text-[12.5px] font-medium text-slate-500"
            title={`${task.attachment_count} attachment${task.attachment_count === 1 ? "" : "s"}`}
          >
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"
              />
            </svg>
            {task.attachment_count}
          </span>
        )}

        {/* The score is not a calibrated probability, so a low one is shown as an instruction
            rather than a number the reader has no way to interpret. Above the threshold the
            percentage stays, where it reads as reassurance and needs no action. */}
        {task.meeting_id !== null &&
          (isLowConfidence(task.confidence) ? (
            <span
              className="ml-auto inline-flex shrink-0 cursor-help items-center gap-1.5 whitespace-nowrap rounded-full bg-amber-50 py-0.5 pl-2 pr-2.5 text-[11.5px] font-medium text-amber-700"
              title={`The AI was unsure about this one (${Math.round(
                task.confidence * 100
              )}% confidence). Check the owner and deadline before relying on it.`}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
              Check this
            </span>
          ) : (
            <span
              className="ml-auto whitespace-nowrap text-[11.5px] tabular-nums text-slate-400"
              title={`The AI is confident this is a real action item (${Math.round(
                task.confidence * 100
              )}%). Items it is unsure about are flagged for review instead.`}
            >
              {Math.round(task.confidence * 100)}% confidence
            </span>
          ))}
      </div>
    </div>
  );
}
