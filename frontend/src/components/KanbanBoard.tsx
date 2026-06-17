"use client";

import { useState } from "react";

import type { Task, TaskStatus } from "@/lib/types";
import TaskCard from "./TaskCard";

const COLUMNS: { status: TaskStatus; title: string; dot: string }[] = [
  { status: "todo", title: "To Do", dot: "bg-slate-400" },
  { status: "in_progress", title: "In Progress", dot: "bg-amber-400" },
  { status: "done", title: "Done", dot: "bg-emerald-500" },
];

interface Props {
  tasks: Task[];
  onStatusChange: (taskId: number, status: TaskStatus) => void;
  onEdit: (task: Task) => void;
  onDelete: (taskId: number) => void;
}

export default function KanbanBoard({ tasks, onStatusChange, onEdit, onDelete }: Props) {
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
              <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-slate-200 text-xs text-slate-400">
                {isDropTarget ? "Drop here" : "No tasks"}
              </div>
            ) : (
              columnTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onDragStart={handleDragStart}
                  onEdit={onEdit}
                  onDelete={onDelete}
                />
              ))
            )}
          </div>
        );
      })}
    </div>
  );
}
