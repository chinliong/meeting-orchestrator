"use client";

import { useState } from "react";

import type { Task, TaskStatus } from "@/lib/types";
import TaskCard from "./TaskCard";

const COLUMNS: { status: TaskStatus; title: string }[] = [
  { status: "todo", title: "To Do" },
  { status: "in_progress", title: "In Progress" },
  { status: "done", title: "Done" },
];

interface Props {
  tasks: Task[];
  onStatusChange: (taskId: number, status: TaskStatus) => void;
  onDelete: (taskId: number) => void;
}

export default function KanbanBoard({ tasks, onStatusChange, onDelete }: Props) {
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
        return (
          <div
            key={column.status}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOverColumn(column.status);
            }}
            onDragLeave={() => setDragOverColumn(null)}
            onDrop={(e) => handleDrop(e, column.status)}
            className={`min-h-[200px] rounded-xl p-3 transition-colors ${
              dragOverColumn === column.status ? "bg-blue-50" : "bg-gray-100"
            }`}
          >
            <h2 className="mb-3 flex items-center justify-between text-sm font-semibold text-gray-600">
              {column.title}
              <span className="rounded-full bg-white px-2 py-0.5 text-xs text-gray-500 shadow-sm">
                {columnTasks.length}
              </span>
            </h2>
            {columnTasks.map((task) => (
              <TaskCard key={task.id} task={task} onDragStart={handleDragStart} onDelete={onDelete} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
