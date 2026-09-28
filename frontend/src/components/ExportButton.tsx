"use client";

import { useEffect, useRef, useState } from "react";

import { isOverdue } from "@/lib/format";
import type { Task } from "@/lib/types";

interface Props {
  /** The tasks the board is showing, filters and search applied. */
  tasks: Task[];
  /** Every task on the board (or the chosen boards), before filters. */
  allTasks: Task[];
  /** Names the file, e.g. the board's name. */
  fileLabel: string;
  /** Board names by id, when the tasks come from several boards; adds a Board column. */
  projectNames?: Map<number, string>;
}

type ColumnKey = "board" | "task" | "owner" | "deadline" | "status" | "meeting" | "meetingDate" | "subtasks" | "overdue";

const STATUS_LABEL: Record<Task["status"], string> = { todo: "To Do", in_progress: "In Progress", done: "Done" };
const STATUS_ORDER: Task["status"][] = ["todo", "in_progress", "done"];

const COLUMNS: { key: ColumnKey; label: string; value: (t: Task, names?: Map<number, string>) => string }[] = [
  { key: "board", label: "Board", value: (t, names) => names?.get(t.project_id) ?? "" },
  { key: "task", label: "Task", value: (t) => t.description },
  { key: "owner", label: "Owner", value: (t) => t.owner ?? "" },
  { key: "deadline", label: "Deadline", value: (t) => t.deadline ?? "" },
  { key: "status", label: "Status", value: (t) => STATUS_LABEL[t.status] },
  { key: "meeting", label: "Meeting", value: (t) => (t.meeting_id === null ? "Added manually" : t.meeting_title ?? "") },
  { key: "meetingDate", label: "Meeting date", value: (t) => t.meeting_date ?? "" },
  // "2 of 5" rather than "2/5", which Excel would read as a date.
  { key: "subtasks", label: "Subtasks done", value: (t) => (t.subtask_total ? `${t.subtask_done} of ${t.subtask_total}` : "") },
  {
    key: "overdue",
    label: "Overdue",
    value: (t) => (t.deadline && t.status !== "done" && isOverdue(t.deadline) ? "Yes" : ""),
  },
];

// Quote a cell when it holds a comma, quote or line break. A cell that starts with = + - or @
// would be run as a formula by Excel, so it is prefixed with an apostrophe (shown as plain text).
function cell(value: string): string {
  const safe = /^[=+\-@]/.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

function toCsv(tasks: Task[], columns: typeof COLUMNS, names?: Map<number, string>): string {
  // Grouped as on the board (To Do, In Progress, Done), earliest deadline first, undated last.
  const rows = [...tasks]
    .sort(
      (a, b) =>
        STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) ||
        (a.deadline ?? "9999").localeCompare(b.deadline ?? "9999")
    )
    .map((t) => columns.map((c) => c.value(t, names)));
  // CRLF line ends, as spreadsheet programs expect.
  return [columns.map((c) => c.label), ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
}

/**
 * "Export" beside Share: opens a small panel to choose which tasks (the ones shown, or all of the
 * board's when a filter is on) and which columns, then downloads them as a CSV file that opens in
 * Excel, Numbers or Google Sheets. Built in the browser from the tasks already loaded, so it needs
 * nothing from the server. On a phone the panel opens as a sheet along the bottom of the screen.
 */
export default function ExportButton({ tasks, allTasks, fileLabel, projectNames }: Props) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<"shown" | "all">("shown");
  const [off, setOff] = useState<Set<ColumnKey>>(new Set());
  const ref = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const filtered = tasks.length < allTasks.length;
  const chosen = filtered && scope === "all" ? allTasks : tasks;
  const available = COLUMNS.filter((c) => c.key !== "board" || projectNames);
  const columns = available.filter((c) => !off.has(c.key));

  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const fileName = `${fileLabel.replace(/[\\/:*?"<>|]+/g, "").trim() || "Tasks"} – ${today}.csv`;

  const toggleColumn = (key: ColumnKey) =>
    setOff((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const download = () => {
    // The byte-order mark makes Excel read the file as UTF-8, so accented names come out right.
    const bom = String.fromCharCode(0xfeff);
    const blob = new Blob([bom, toCsv(chosen, columns, projectNames)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.click();
    URL.revokeObjectURL(url);
    setOpen(false);
  };

  const plural = (n: number) => `${n} task${n === 1 ? "" : "s"}`;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => {
          setScope("shown");
          setOpen((v) => !v);
        }}
        disabled={allTasks.length === 0}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={allTasks.length === 0 ? "No tasks to export" : "Download tasks as a spreadsheet (CSV)"}
        aria-label="Export to spreadsheet"
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-900/5 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-600"
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
          <path d="M10.75 2.75a.75.75 0 00-1.5 0v8.69L6.28 8.47a.75.75 0 00-1.06 1.06l4.25 4.25a.75.75 0 001.06 0l4.25-4.25a.75.75 0 10-1.06-1.06l-2.97 2.97V2.75z" />
          <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
        </svg>
        Export
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Export to spreadsheet"
          className="fixed inset-x-4 bottom-4 z-40 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-2xl sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:mt-1.5 sm:w-80 sm:rounded-xl sm:shadow-lg"
        >
          <p className="font-display text-sm font-bold text-slate-900">Export to spreadsheet</p>

          {filtered && (
            <fieldset className="mt-3">
              <legend className="text-xs font-medium uppercase tracking-wide text-slate-400">Tasks</legend>
              {(
                [
                  ["shown", `The ${plural(tasks.length)} shown`, "with your filters"],
                  ["all", `All ${plural(allTasks.length)}`, "ignoring the filters"],
                ] as const
              ).map(([value, label, hint]) => (
                <label key={value} className="mt-1.5 flex cursor-pointer items-center gap-2.5 text-sm text-slate-700">
                  <input
                    type="radio"
                    name="export-scope"
                    checked={scope === value}
                    onChange={() => setScope(value)}
                    className="h-4 w-4 accent-[#0E1626]"
                  />
                  <span>
                    {label} <span className="text-slate-400">{hint}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          )}

          <fieldset className="mt-3">
            <legend className="text-xs font-medium uppercase tracking-wide text-slate-400">Columns</legend>
            <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1.5">
              {available.map((c) => (
                <label
                  key={c.key}
                  className={`flex items-center gap-2 text-sm ${c.key === "task" ? "text-slate-400" : "cursor-pointer text-slate-700"}`}
                >
                  <input
                    type="checkbox"
                    checked={!off.has(c.key)}
                    disabled={c.key === "task"}
                    onChange={() => toggleColumn(c.key)}
                    className="h-4 w-4 shrink-0 rounded border-slate-300 accent-[#0E1626]"
                  />
                  {c.label}
                </label>
              ))}
            </div>
          </fieldset>

          <button
            type="button"
            onClick={download}
            disabled={chosen.length === 0}
            className="mt-4 w-full rounded-lg bg-ink px-3 py-2 text-sm font-medium text-white transition hover:bg-ink-700 disabled:opacity-50"
          >
            Download {plural(chosen.length)}
          </button>
          <p className="mt-1.5 truncate text-center text-xs text-slate-400" title={fileName}>
            {fileName}
          </p>
        </div>
      )}
    </div>
  );
}
