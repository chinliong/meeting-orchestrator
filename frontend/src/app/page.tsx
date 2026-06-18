"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AuthGate from "@/components/AuthGate";
import EditTaskModal from "@/components/EditTaskModal";
import Filters from "@/components/Filters";
import KanbanBoard from "@/components/KanbanBoard";
import ProjectModal from "@/components/ProjectModal";
import ShareModal from "@/components/ShareModal";
import StatsBar from "@/components/StatsBar";
import TopBar from "@/components/TopBar";
import TranscriptUpload from "@/components/TranscriptUpload";
import { api, setAuthToken, setWorkspaceToken } from "@/lib/api";
import {
  clearAuth,
  clearGuestChosen,
  clearGuestWorkspaces,
  isGuestChosen,
  loadAuth,
  loadGuestWorkspaces,
  removeGuestWorkspace,
  saveAuth,
  setGuestChosen,
  upsertGuestWorkspace,
  workspaceTokenFor,
} from "@/lib/session";
import type { AuthResponse, Project, Task, TaskStatus, User } from "@/lib/types";

type Session = { mode: "user"; user: User } | { mode: "guest" } | null;

export default function DashboardPage() {
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<Session>(null);
  const [showAuth, setShowAuth] = useState(false); // guest upgrade overlay

  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedOwner, setSelectedOwner] = useState("");
  const [sortByDeadline, setSortByDeadline] = useState(false);
  const [search, setSearch] = useState("");
  const [searchAllProjects, setSearchAllProjects] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [projectModal, setProjectModal] = useState<"create" | "edit" | null>(null);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [creatingTask, setCreatingTask] = useState(false);
  const [shareProject, setShareProject] = useState<Project | null>(null);

  const user = session?.mode === "user" ? session.user : null;

  // --- bootstrap: decide session, load boards, honour a ?w=<token> share link ---
  useEffect(() => {
    (async () => {
      const url = new URL(window.location.href);
      const wToken = url.searchParams.get("w");
      const stored = loadAuth();

      let sess: Session = null;
      if (stored) {
        setAuthToken(stored.token);
        sess = { mode: "user", user: stored.user };
      } else if (wToken || isGuestChosen()) {
        sess = { mode: "guest" };
      }
      setSession(sess);

      let projs: Project[] = [];
      if (sess?.mode === "user") {
        try {
          projs = await api.listProjects();
        } catch (err) {
          setLoadError((err as Error).message);
        }
      } else if (sess?.mode === "guest") {
        projs = loadGuestWorkspaces();
      }

      if (wToken) {
        try {
          const shared = await api.getProjectByToken(wToken);
          if (sess?.mode === "user") {
            if (!projs.some((p) => p.id === shared.id)) projs = [shared, ...projs];
          } else {
            projs = upsertGuestWorkspace(shared);
            if (!isGuestChosen()) setGuestChosen();
          }
          setSelectedProjectId(shared.id);
        } catch (err) {
          setLoadError((err as Error).message);
        }
        url.searchParams.delete("w");
        window.history.replaceState({}, "", url.pathname);
        setProjects(projs);
      } else {
        setProjects(projs);
        if (projs.length > 0) setSelectedProjectId(projs[0].id);
      }
      setReady(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;
  const canEdit = selectedProject?.access_level === "edit";

  const projectNames = useMemo(
    () => new Map(projects.map((p) => [p.id, p.name])),
    [projects]
  );

  // Set the active board's capability token, then (re)load its tasks.
  const reloadTasks = useCallback(() => {
    if (searchAllProjects && session?.mode === "user") {
      setWorkspaceToken(null);
      api.listTasks({}).then(setTasks).catch((err) => setLoadError(err.message));
      return;
    }
    const proj = projects.find((p) => p.id === selectedProjectId) ?? null;
    setWorkspaceToken(proj ? workspaceTokenFor(proj) : null);
    if (selectedProjectId) {
      api
        .listTasks({ projectId: selectedProjectId })
        .then(setTasks)
        .catch((err) => setLoadError(err.message));
    } else {
      setTasks([]);
    }
  }, [selectedProjectId, searchAllProjects, projects, session]);

  useEffect(() => {
    if (ready) reloadTasks();
  }, [ready, reloadTasks]);

  const owners = useMemo(
    () => Array.from(new Set(tasks.map((t) => t.owner).filter(Boolean))) as string[],
    [tasks]
  );

  const visibleTasks = useMemo(() => {
    let result = selectedOwner ? tasks.filter((t) => t.owner === selectedOwner) : tasks;
    const q = search.trim().toLowerCase();
    if (q) {
      result = result.filter((t) =>
        [t.description, t.owner, t.meeting_title]
          .filter(Boolean)
          .some((field) => (field as string).toLowerCase().includes(q))
      );
    }
    if (sortByDeadline) {
      result = [...result].sort((a, b) => {
        if (!a.deadline) return 1;
        if (!b.deadline) return -1;
        return a.deadline.localeCompare(b.deadline);
      });
    }
    return result;
  }, [tasks, selectedOwner, sortByDeadline, search]);

  // --- task handlers ---
  const handleStatusChange = async (taskId: number, status: TaskStatus) => {
    setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, status } : t)));
    await api.updateTask(taskId, { status });
  };

  const handleEditTask = async (
    taskId: number,
    patch: { description?: string; owner?: string | null; deadline?: string | null; status?: TaskStatus }
  ) => {
    const updated = await api.updateTask(taskId, patch);
    setTasks((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
  };

  const handleCreateTask = async (values: {
    description: string;
    owner: string | null;
    deadline: string | null;
    status: TaskStatus;
  }) => {
    if (!selectedProjectId) return;
    const created = await api.createTask({ projectId: selectedProjectId, ...values });
    setTasks((prev) => [created, ...prev]);
  };

  const handleRenameMeeting = async (meetingId: number, title: string) => {
    const updated = await api.updateMeeting(meetingId, title);
    setTasks((prev) =>
      prev.map((t) => (t.meeting_id === meetingId ? { ...t, meeting_title: updated.title } : t))
    );
  };

  const handleDelete = async (taskId: number) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    await api.deleteTask(taskId);
  };

  const handleTranscriptSubmit = async (title: string, transcriptText: string) => {
    if (!selectedProjectId) return;
    await api.submitTranscript(selectedProjectId, title, transcriptText);
    reloadTasks();
  };

  const handleAudioSubmit = async (title: string, file: File) => {
    if (!selectedProjectId) return;
    const meeting = await api.submitAudio(selectedProjectId, title, file);
    const deadline = Date.now() + 5 * 60 * 1000;
    let current = meeting;
    while (current.status === "processing" || current.status === "pending") {
      if (Date.now() > deadline) {
        throw new Error("Transcription is taking too long. Please try again or use a shorter file.");
      }
      await new Promise((resolve) => setTimeout(resolve, 2500));
      current = await api.getMeeting(meeting.id);
    }
    if (current.status === "failed") {
      throw new Error(current.error_message || "Transcription failed.");
    }
    reloadTasks();
  };

  // --- project handlers ---
  const handleCreateProject = async (name: string, description: string) => {
    const project = await api.createProject(name, description);
    if (user) setProjects((prev) => [project, ...prev]);
    else setProjects(upsertGuestWorkspace(project));
    setSelectedProjectId(project.id);
    setTasks([]);
  };

  const handleUpdateProject = async (name: string, description: string) => {
    if (!selectedProjectId) return;
    const updated = await api.updateProject(selectedProjectId, { name, description });
    setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    if (!user) upsertGuestWorkspace(updated);
  };

  const handleDeleteProject = async () => {
    if (!selectedProjectId) return;
    if (!window.confirm("Delete this project and all its meetings and tasks? This cannot be undone."))
      return;
    await api.deleteProject(selectedProjectId);
    const remaining = projects.filter((p) => p.id !== selectedProjectId);
    setProjects(remaining);
    if (!user) removeGuestWorkspace(selectedProjectId);
    setSelectedProjectId(remaining[0]?.id ?? null);
    setTasks([]);
  };

  // --- auth handlers ---
  const claimTokens = useMemo(
    () => projects.map((p) => p.edit_token).filter((t): t is string => !!t),
    [projects]
  );

  const handleAuthed = async (auth: AuthResponse) => {
    saveAuth(auth);
    setAuthToken(auth.token);
    clearGuestChosen();
    clearGuestWorkspaces();
    setSession({ mode: "user", user: auth.user });
    setShowAuth(false);
    try {
      const projs = await api.listProjects();
      setProjects(projs);
      setSelectedProjectId(projs[0]?.id ?? null);
    } catch (err) {
      setLoadError((err as Error).message);
    }
  };

  const handleContinueAsGuest = () => {
    setGuestChosen();
    setSession({ mode: "guest" });
    const projs = loadGuestWorkspaces();
    setProjects(projs);
    setSelectedProjectId(projs[0]?.id ?? null);
  };

  const handleLogout = () => {
    clearAuth();
    setAuthToken(null);
    setWorkspaceToken(null);
    setSession(null);
    setProjects([]);
    setTasks([]);
    setSelectedProjectId(null);
  };

  if (!ready) {
    return <div className="min-h-screen" />;
  }

  // Full-page gate when no session has been chosen yet.
  if (session === null) {
    return (
      <div className="min-h-screen px-6">
        <AuthGate claimTokens={[]} onAuthed={handleAuthed} onGuest={handleContinueAsGuest} />
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <TopBar
        projects={projects}
        selectedProjectId={selectedProjectId}
        onSelectProject={setSelectedProjectId}
        onNewProject={() => setProjectModal("create")}
        user={user}
        onLogin={() => setShowAuth(true)}
        onLogout={handleLogout}
      />

      <main className="mx-auto max-w-7xl px-6 py-6">
        {loadError && (
          <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {loadError}
          </p>
        )}

        {projects.length === 0 ? (
          <EmptyProjects onCreate={() => setProjectModal("create")} />
        ) : (
          <>
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-xl font-bold text-slate-900">{selectedProject?.name}</h2>
                  {!canEdit && (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                      View only
                    </span>
                  )}
                </div>
                {selectedProject?.description && (
                  <p className="mt-0.5 text-sm text-slate-500">{selectedProject.description}</p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  onClick={() => setShareProject(selectedProject)}
                  className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-500 ring-1 ring-slate-200 transition hover:bg-slate-50 hover:text-slate-700"
                  title="Share this board"
                >
                  <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                    <path d="M13 4.5a2.5 2.5 0 11.7 1.74l-4.3 2.5a2.5 2.5 0 010 2.52l4.3 2.5a2.5 2.5 0 11-.76 1.3l-4.3-2.5a2.5 2.5 0 110-4.12l4.3-2.5A2.5 2.5 0 0113 4.5z" />
                  </svg>
                  Share
                </button>
                {canEdit && (
                  <>
                    <button
                      onClick={() => setProjectModal("edit")}
                      className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-500 ring-1 ring-slate-200 transition hover:bg-slate-50 hover:text-slate-700"
                      title="Rename project"
                    >
                      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.879.506l-3.012.86a.5.5 0 01-.617-.617l.86-3.012a2 2 0 01.506-.879l8.5-8.5z" />
                      </svg>
                      Rename
                    </button>
                    <button
                      onClick={handleDeleteProject}
                      className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-500 ring-1 ring-slate-200 transition hover:bg-rose-50 hover:text-rose-600 hover:ring-rose-200"
                      title="Delete project"
                    >
                      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                        <path d="M8 2a1 1 0 00-1 1v1H4.5a.5.5 0 000 1H5v10a2 2 0 002 2h6a2 2 0 002-2V5h.5a.5.5 0 000-1H13V3a1 1 0 00-1-1H8zm1 2V3h2v1H9zM8 7a.75.75 0 01.75.75v6a.75.75 0 01-1.5 0v-6A.75.75 0 018 7zm4.75.75a.75.75 0 00-1.5 0v6a.75.75 0 001.5 0v-6z" />
                      </svg>
                      Delete
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="mb-6">
              <StatsBar tasks={tasks} />
            </div>

            <div className={canEdit ? "grid gap-6 lg:grid-cols-[340px_1fr]" : ""}>
              {canEdit && (
                <div className="lg:sticky lg:top-20 lg:self-start">
                  <TranscriptUpload onSubmitText={handleTranscriptSubmit} onSubmitAudio={handleAudioSubmit} />
                </div>
              )}

              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative min-w-[200px] flex-1">
                    <svg
                      viewBox="0 0 20 20"
                      className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                      fill="currentColor"
                    >
                      <path
                        fillRule="evenodd"
                        d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
                        clipRule="evenodd"
                      />
                    </svg>
                    <input
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search tasks, owners, meetings..."
                      className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-9 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
                    />
                    {search && (
                      <button
                        onClick={() => setSearch("")}
                        aria-label="Clear search"
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                      >
                        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                        </svg>
                      </button>
                    )}
                  </div>

                  {user && projects.length > 1 && (
                    <div className="flex shrink-0 rounded-lg bg-slate-100 p-1 text-sm font-medium">
                      <button
                        onClick={() => setSearchAllProjects(false)}
                        className={`rounded-md px-3 py-1 transition ${
                          searchAllProjects ? "text-slate-500 hover:text-slate-700" : "bg-white text-slate-900 shadow-sm"
                        }`}
                      >
                        This project
                      </button>
                      <button
                        onClick={() => setSearchAllProjects(true)}
                        className={`rounded-md px-3 py-1 transition ${
                          searchAllProjects ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
                        }`}
                      >
                        All projects
                      </button>
                    </div>
                  )}
                  {canEdit && (
                    <button
                      onClick={() => setCreatingTask(true)}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
                    >
                      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                        <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
                      </svg>
                      Add task
                    </button>
                  )}
                </div>

                {owners.length > 0 && (
                  <Filters
                    owners={owners}
                    selectedOwner={selectedOwner}
                    onOwnerChange={setSelectedOwner}
                    sortByDeadline={sortByDeadline}
                    onSortToggle={() => setSortByDeadline((v) => !v)}
                  />
                )}

                {search.trim() && visibleTasks.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-200 bg-white/60 px-4 py-12 text-center text-sm text-slate-500">
                    No tasks match <span className="font-medium text-slate-700">“{search.trim()}”</span>.
                  </div>
                ) : (
                  <KanbanBoard
                    tasks={visibleTasks}
                    projectNames={searchAllProjects ? projectNames : undefined}
                    canEdit={!!canEdit}
                    onStatusChange={handleStatusChange}
                    onEdit={setEditingTask}
                    onDelete={handleDelete}
                    onRenameMeeting={handleRenameMeeting}
                  />
                )}
              </div>
            </div>
          </>
        )}
      </main>

      {showAuth && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 backdrop-blur-sm"
          onMouseDown={() => setShowAuth(false)}
        >
          <div onMouseDown={(e) => e.stopPropagation()}>
            <AuthGate
              claimTokens={claimTokens}
              onAuthed={handleAuthed}
              onGuest={handleContinueAsGuest}
              allowGuest={false}
              onCancel={() => setShowAuth(false)}
            />
          </div>
        </div>
      )}

      <ProjectModal
        open={projectModal !== null}
        mode={projectModal ?? "create"}
        initialName={projectModal === "edit" ? selectedProject?.name ?? "" : ""}
        initialDescription={projectModal === "edit" ? selectedProject?.description ?? "" : ""}
        onClose={() => setProjectModal(null)}
        onSubmit={projectModal === "edit" ? handleUpdateProject : handleCreateProject}
      />

      <EditTaskModal
        task={editingTask}
        createMode={creatingTask}
        onClose={() => {
          setEditingTask(null);
          setCreatingTask(false);
        }}
        onSave={handleEditTask}
        onCreate={handleCreateTask}
      />

      <ShareModal project={shareProject} onClose={() => setShareProject(null)} />
    </div>
  );
}

function EmptyProjects({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-card">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-slate-900">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor">
          <path d="M3 6a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V6z" />
        </svg>
      </div>
      <h2 className="text-lg font-semibold text-slate-900">No projects yet</h2>
      <p className="mt-1 text-sm text-slate-500">
        Create a project to start turning meeting transcripts into tracked action items.
      </p>
      <button
        onClick={onCreate}
        className="mt-5 inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
        </svg>
        Create your first project
      </button>
    </div>
  );
}
