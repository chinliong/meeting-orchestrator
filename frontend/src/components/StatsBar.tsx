"use client";

import type { Task } from "@/lib/types";
import { isOverdue } from "@/lib/format";

interface Props {
  tasks: Task[];
  /** What the counts are narrowed to by the board's filters, e.g. a meeting or an owner; null for the whole board. */
  scope?: string | null;
}

/**
 * The board's counts in one card: To Do, In Progress, Done and Overdue side by side (two by two on
 * a phone), each with a short caption, over a thin strip showing how the tasks split across the
 * three columns.
 */
export default function StatsBar({ tasks, scope = null }: Props) {
  const todo = tasks.filter((t) => t.status === "todo").length;
  const inProgress = tasks.filter((t) => t.status === "in_progress").length;
  const done = tasks.filter((t) => t.status === "done").length;
  const overdue = tasks.filter(
    (t) => t.deadline && t.status !== "done" && isOverdue(t.deadline)
  ).length;
  const total = todo + inProgress + done;
  const share = (n: number) => (total ? (n / total) * 100 : 0);
  const pctDone = Math.round(share(done));

  const cells = [
    { label: "To Do", value: todo, dot: "bg-status-todo", caption: "not started" },
    { label: "In Progress", value: inProgress, dot: "bg-status-progress", caption: "under way" },
    { label: "Done", value: done, dot: "bg-status-done", caption: total ? `${pctDone}% complete` : "nothing yet" },
    {
      label: "Overdue",
      value: overdue,
      dot: "bg-rose-500",
      caption: overdue ? "past their deadline" : "all on time",
      danger: overdue > 0,
    },
  ];

  return (
    <section aria-label="Board summary" className="overflow-hidden rounded-xl border border-slate-200/80 bg-white">
      {scope && (
        <p className="flex items-center gap-1.5 border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
          <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="currentColor" aria-hidden>
            <path d="M3 5a1 1 0 011-1h12a1 1 0 01.8 1.6L12 12v4a1 1 0 01-1.45.9l-2-1A1 1 0 018 15v-3L3.2 5.6A1 1 0 013 5z" />
          </svg>
          <span className="truncate">
            Counts for <span className="font-medium text-slate-700">{scope}</span>
          </span>
        </p>
      )}
      {/* The 1px gaps over a tinted background draw the dividers, in both the 4- and 2-column layouts. */}
      <div className="grid grid-cols-2 gap-px bg-slate-100 sm:grid-cols-4">
        {cells.map((c) => (
          <div key={c.label} className="bg-white px-4 py-3">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${c.dot}`} aria-hidden />
              <span className="font-display text-xs font-semibold uppercase tracking-wide text-slate-500">{c.label}</span>
            </div>
            <p
              className={`mt-1 font-display text-3xl font-bold tabular-nums tracking-tight ${
                c.danger ? "text-rose-600" : "text-slate-900"
              }`}
            >
              {c.value}
            </p>
            <p className={`text-xs ${c.danger ? "text-rose-500" : "text-slate-400"}`}>{c.caption}</p>
          </div>
        ))}
      </div>
      {/* How the tasks split across the three columns, in the columns' colours. */}
      <div
        role="img"
        aria-label={`${todo} to do, ${inProgress} in progress, ${done} done`}
        className="flex h-1 w-full bg-slate-100"
      >
        <span className="h-full bg-status-todo transition-[width] duration-500" style={{ width: `${share(todo)}%` }} />
        <span className="h-full bg-status-progress transition-[width] duration-500" style={{ width: `${share(inProgress)}%` }} />
        <span className="h-full bg-status-done transition-[width] duration-500" style={{ width: `${share(done)}%` }} />
      </div>
    </section>
  );
}
