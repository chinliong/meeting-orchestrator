"use client";

import { useEffect, useMemo, useState } from "react";

import Filters from "@/components/Filters";
import KanbanBoard from "@/components/KanbanBoard";
import NewProjectModal from "@/components/NewProjectModal";
import StatsBar from "@/components/StatsBar";
import TopBar from "@/components/TopBar";
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
  const [modalOpen, setModalOpen] = useState(false);

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

  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;

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

  const handleAudioSubmit = async (title: string, file: File) => {
    if (!selectedProjectId) return;
    await api.submitAudio(selectedProjectId, title, file);
    refreshTasks(selectedProjectId);
  };

  const handleCreateProject = async (name: string, description: string) => {
    const project = await api.createProject(name, description);
    setProjects((prev) => [project, ...prev]);
    setSelectedProjectId(project.id);
    setTasks([]);
  };

  return (
    <div className="min-h-screen">
      <TopBar
        projects={projects}
        selectedProjectId={selectedProjectId}
        onSelectProject={setSelectedProjectId}
        onNewProject={() => setModalOpen(true)}
      />

      <main className="mx-auto max-w-7xl px-6 py-6">
        {loadError && (
          <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {loadError}. Is the backend reachable at the configured API base URL?
          </p>
        )}

        {projects.length === 0 ? (
          <EmptyProjects onCreate={() => setModalOpen(true)} hasError={!!loadError} />
        ) : (
          <>
            <div className="mb-5">
              <h2 className="text-xl font-bold text-slate-900">{selectedProject?.name}</h2>
              {selectedProject?.description && (
                <p className="mt-0.5 text-sm text-slate-500">{selectedProject.description}</p>
              )}
            </div>

            <div className="mb-6">
              <StatsBar tasks={tasks} />
            </div>

            <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
              <div className="lg:sticky lg:top-20 lg:self-start">
                <TranscriptUpload
                  onSubmitText={handleTranscriptSubmit}
                  onSubmitAudio={handleAudioSubmit}
                />
              </div>

              <div className="space-y-4">
                {owners.length > 0 && (
                  <Filters
                    owners={owners}
                    selectedOwner={selectedOwner}
                    onOwnerChange={setSelectedOwner}
                    sortByDeadline={sortByDeadline}
                    onSortToggle={() => setSortByDeadline((v) => !v)}
                  />
                )}
                <KanbanBoard
                  tasks={visibleTasks}
                  onStatusChange={handleStatusChange}
                  onDelete={handleDelete}
                />
              </div>
            </div>
          </>
        )}
      </main>

      <NewProjectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreate={handleCreateProject}
      />
    </div>
  );
}

function EmptyProjects({ onCreate, hasError }: { onCreate: () => void; hasError: boolean }) {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-card">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor">
          <path d="M3 6a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V6z" />
        </svg>
      </div>
      <h2 className="text-lg font-semibold text-slate-900">
        {hasError ? "No projects loaded" : "No projects yet"}
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        Create a project to start turning meeting transcripts into tracked action items.
      </p>
      <button
        onClick={onCreate}
        className="mt-5 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700"
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
        </svg>
        Create your first project
      </button>
    </div>
  );
}
