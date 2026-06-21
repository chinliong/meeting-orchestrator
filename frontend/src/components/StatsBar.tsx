"use client";

import type { Task } from "@/lib/types";
import { isOverdue } from "@/lib/format";

interface Props {
  tasks: Task[];
}

export default function StatsBar({ tasks }: Props) {
  const todo = tasks.filter((t) => t.status === "todo").length;
  const inProgress = tasks.filter((t) => t.status === "in_progress").length;
  const done = tasks.filter((t) => t.status === "done").length;
  const overdue = tasks.filter(
    (t) => t.deadline && t.status !== "done" && isOverdue(t.deadline)
  ).length;

  const cards = [
    { label: "To Do", value: todo, dot: "bg-brand", arc: "text-brand" },
    { label: "In Progress", value: inProgress, dot: "bg-amber-400", arc: "text-amber-400" },
    { label: "Done", value: done, dot: "bg-emerald-500", arc: "text-emerald-500" },
    { label: "Overdue", value: overdue, dot: "bg-rose-500", arc: "text-rose-500", danger: overdue > 0 },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-4 shadow-card transition hover:-translate-y-0.5 hover:shadow-card-hover"
        >
          {/* Concentric-arc ornament, tinted to the metric — the geometric throughline. */}
          <span
            className={`pointer-events-none absolute -bottom-7 -right-7 h-[5.5rem] w-[5.5rem] rounded-full border-2 opacity-[0.16] ${c.arc}`}
            style={{ borderColor: "currentColor" }}
          />
          <span
            className={`pointer-events-none absolute -bottom-3.5 -right-3.5 h-14 w-14 rounded-full border-2 opacity-[0.26] ${c.arc}`}
            style={{ borderColor: "currentColor" }}
          />
          <div className="relative flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${c.dot}`} />
            <span className="font-display text-xs font-semibold uppercase tracking-wide text-slate-500">{c.label}</span>
          </div>
          <p
            className={`relative mt-3 font-display text-4xl font-bold tracking-tight ${
              c.danger ? "text-rose-600" : "text-slate-900"
            }`}
          >
            {c.value}
          </p>
        </div>
      ))}
    </div>
  );
}
