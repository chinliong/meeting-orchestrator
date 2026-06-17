"use client";

import { useEffect, useMemo, useState } from "react";

import Filters from "@/components/Filters";
import KanbanBoard from "@/components/KanbanBoard";
import TranscriptUpload from "@/components/TranscriptUpload";
import { api } from "@/lib/api";
import type { Project, Task, TaskStatus } from "@/lib/types";

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedOwner, setSelectedOwner] = useState("");
  const [sortByDeadline, setSortByDeadline] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listProjects()
      .then((data) => {
        setProjects(data);
        if (data.length > 0) setSelectedProjectId(data[0].id);
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  const refreshTasks = (projectId: number) => {
    api
      .listTasks({ projectId })
      .then(setTasks)
      .catch((err) => setLoadError(err.message));
  };

  useEffect(() => {
    if (selectedProjectId) refreshTasks(selectedProjectId);
  }, [selectedProjectId]);

  const owners = useMemo(
    () => Array.from(new Set(tasks.map((t) => t.owner).filter(Boolean))) as string[],
    [tasks]
  );

  const visibleTasks = useMemo(() => {
    let result = selectedOwner ? tasks.filter((t) => t.owner === selectedOwner) : tasks;
    if (sortByDeadline) {
      result = [...result].sort((a, b) => {
        if (!a.deadline) return 1;
        if (!b.deadline) return -1;
        return a.deadline.localeCompare(b.deadline);
      });
    }
    return result;
  }, [tasks, selectedOwner, sortByDeadline]);

  const handleStatusChange = async (taskId: number, status: TaskStatus) => {
    setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, status } : t)));
    await api.updateTask(taskId, { status });
  };

  const handleDelete = async (taskId: number) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    await api.deleteTask(taskId);
  };

  const handleTranscriptSubmit = async (title: string, transcriptText: string) => {
    if (!selectedProjectId) return;
    await api.submitTranscript(selectedProjectId, title, transcriptText);
    refreshTasks(selectedProjectId);
  };

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-gray-900">Meeting & Workflow Orchestrator</h1>
        {projects.length > 0 && (
          <select
            value={selectedProjectId ?? ""}
            onChange={(e) => setSelectedProjectId(Number(e.target.value))}
            className="rounded border border-gray-300 px-3 py-2 text-sm"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {loadError && (
        <p className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">
          {loadError}. Is the backend running at the configured API base URL?
        </p>
      )}

      <TranscriptUpload onSubmit={handleTranscriptSubmit} />

      <Filters
        owners={owners}
        selectedOwner={selectedOwner}
        onOwnerChange={setSelectedOwner}
        sortByDeadline={sortByDeadline}
        onSortToggle={() => setSortByDeadline((v) => !v)}
      />

      <KanbanBoard tasks={visibleTasks} onStatusChange={handleStatusChange} onDelete={handleDelete} />
    </main>
  );
}
