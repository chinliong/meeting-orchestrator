"use client";

import { useState } from "react";

import type { Task, TaskStatus } from "@/lib/types";
import TaskCard from "./TaskCard";

const COLUMNS: { status: TaskStatus; title: string; dot: string; empty: string }[] = [
  { status: "todo", title: "To Do", dot: "bg-slate-400", empty: "Nothing to do yet" },
  { status: "in_progress", title: "In Progress", dot: "bg-amber-400", empty: "Nothing in progress" },
  { status: "done", title: "Done", dot: "bg-emerald-500", empty: "Nothing done yet" },
];

interface Props {
  tasks: Task[];
  /** When set, each card shows which project it belongs to (cross-project view). */
  projectNames?: Map<number, string>;
  onStatusChange: (taskId: number, status: TaskStatus) => void;
  onEdit: (task: Task) => void;
  onDelete: (taskId: number) => void;
  onRenameMeeting: (meetingId: number, title: string) => Promise<void>;
}

export default function KanbanBoard({
  tasks,
  projectNames,
  onStatusChange,
  onEdit,
  onDelete,
  onRenameMeeting,
}: Props) {
  const [dragOverColumn, setDragOverColumn] = useState<TaskStatus | null>(null);

  const handleDragStart = (e: React.DragEvent, task: Task) => {
    e.dataTransfer.setData("taskId", String(task.id));
  };

  const handleDrop = (e: React.DragEvent, status: TaskStatus) => {
    e.preventDefault();
    setDragOverColumn(null);
    const taskId = Number(e.dataTransfer.getData("taskId"));
    if (taskId) onStatusChange(taskId, status);
  };

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {COLUMNS.map((column) => {
        const columnTasks = tasks.filter((t) => t.status === column.status);
        const isDropTarget = dragOverColumn === column.status;
        return (
          <div
            key={column.status}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOverColumn(column.status);
            }}
            onDragLeave={() => setDragOverColumn(null)}
            onDrop={(e) => handleDrop(e, column.status)}
            className={`flex min-h-[240px] flex-col rounded-xl border p-3 transition-colors ${
              isDropTarget
                ? "border-slate-400 bg-slate-200/70"
                : "border-slate-200 bg-slate-100/70"
            }`}
          >
            <div className="mb-3 flex items-center gap-2 px-1">
              <span className={`h-2 w-2 rounded-full ${column.dot}`} />
              <h2 className="text-sm font-semibold text-slate-700">{column.title}</h2>
              <span className="ml-auto rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-500 shadow-sm">
                {columnTasks.length}
              </span>
            </div>

            {columnTasks.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-200 py-8 text-slate-300">
                {isDropTarget ? (
                  <span className="text-xs font-medium text-slate-500">Drop here</span>
                ) : (
                  <>
                    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.6">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-7 8h8a2 2 0 002-2V7.5L14.5 3H7a2 2 0 00-2 2v13a2 2 0 002 2z" />
                    </svg>
                    <span className="text-xs">{column.empty}</span>
                  </>
                )}
              </div>
            ) : (
              columnTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  projectName={projectNames?.get(task.project_id) ?? null}
                  onDragStart={handleDragStart}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  onRenameMeeting={onRenameMeeting}
                />
              ))
            )}
          </div>
        );
      })}
    </div>
  );
}
