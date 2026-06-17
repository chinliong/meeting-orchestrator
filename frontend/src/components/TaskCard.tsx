"use client";

import type { Task } from "@/lib/types";

interface Props {
  task: Task;
  onDragStart: (e: React.DragEvent, task: Task) => void;
  onDelete: (id: number) => void;
}

export default function TaskCard({ task, onDragStart, onDelete }: Props) {
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, task)}
      className="mb-3 cursor-grab rounded-lg border border-gray-200 bg-white p-3 shadow-sm active:cursor-grabbing"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-gray-800">{task.description}</p>
        <button
          onClick={() => onDelete(task.id)}
          className="text-xs text-gray-400 hover:text-red-500"
          aria-label="Delete task"
        >
          ✕
        </button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
        {task.owner && (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-blue-700">{task.owner}</span>
        )}
        {task.deadline && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700">
            Due {task.deadline}
          </span>
        )}
        <span className="rounded-full bg-gray-100 px-2 py-0.5">
          {Math.round(task.confidence * 100)}% confidence
        </span>
      </div>
    </div>
  );
}
