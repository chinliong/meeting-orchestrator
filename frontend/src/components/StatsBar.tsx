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
    { label: "To Do", value: todo, dot: "bg-slate-400" },
    { label: "In Progress", value: inProgress, dot: "bg-amber-400" },
    { label: "Done", value: done, dot: "bg-emerald-500" },
    { label: "Overdue", value: overdue, dot: "bg-rose-500", danger: overdue > 0 },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-xl border border-slate-200 bg-white p-4 shadow-card"
        >
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${c.dot}`} />
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {c.label}
            </span>
          </div>
          <p
            className={`mt-2 text-2xl font-semibold ${
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
