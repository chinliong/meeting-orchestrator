"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import AccountModal from "@/components/AccountModal";
import AuthGate from "@/components/AuthGate";
import CalendarView from "@/components/CalendarView";
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
  updateStoredUser,
  upsertGuestWorkspace,
  workspaceTokenFor,
} from "@/lib/session";
import type { AuthResponse, Project, Task, TaskMeta, TaskStatus, UndoAction, User } from "@/lib/types";

type Session = { mode: "user"; user: User } | { mode: "guest" } | null;
type BoardView = "board" | "calendar";

// Render's free tier sleeps after inactivity, so the first request cold-starts (~30-60s).
// Poll health up front so the rest of bootstrap hits a warm server; cap the wait so a truly
// down backend still lets the app render and surface a real error.
async function waitForBackend(): Promise<void> {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    try {
      await api.health();
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
}

export default function DashboardPage() {
  const [ready, setReady] = useState(false);
  const [slow, setSlow] = useState(false); // backend is taking a while (likely a cold start)
  const [session, setSession] = useState<Session>(null);
  const [showAuth, setShowAuth] = useState(false); // guest upgrade overlay
  const [showAccount, setShowAccount] = useState(false); // account settings overlay

  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedOwner, setSelectedOwner] = useState("");
  const [sortByDeadline, setSortByDeadline] = useState(false);
  const [view, setView] = useState<BoardView>("board");
  const [search, setSearch] = useState("");
  const [searchAllProjects, setSearchAllProjects] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [projectModal, setProjectModal] = useState<"create" | "edit" | null>(null);
  // The card edits a *live* task looked up by id, so changes (incl. undo) flow back into it.
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null);
  // Bumped on every undo so the open card re-seeds its fields from the reverted task.
  const [undoNonce, setUndoNonce] = useState(0);
  // Bumped when an undo reverses a subtask change, so the open subtask list re-fetches.
  const [subtaskReloadNonce, setSubtaskReloadNonce] = useState(0);
  const [creatingTask, setCreatingTask] = useState(false);
  const [shareProject, setShareProject] = useState<Project | null>(null);

  const user = session?.mode === "user" ? session.user : null;

  // While bootstrapping, escalate the loader message if the backend is slow to answer.
  useEffect(() => {
    if (ready) return;
    const timer = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(timer);
  }, [ready]);

  // --- bootstrap: decide session, load boards, honour a ?w=<token> share link ---
  useEffect(() => {
    (async () => {
      // Wait for the (possibly cold-starting) backend before any real requests.
      await waitForBackend();

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

  // The task the card is editing, resolved live from state so edits/undo are reflected.
  const editingTask = editingTaskId != null ? tasks.find((t) => t.id === editingTaskId) ?? null : null;

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

  // Calendar plots task deadlines; it works in any task view (single board or across all).
  const activeView: BoardView = view;

  // --- undo: a shared stack whose entries each perform the inverse of an action ---
  const undoStackRef = useRef<UndoAction[]>([]);
  const [undoDepth, setUndoDepth] = useState(0);

  const pushUndo = useCallback((action: UndoAction) => {
    undoStackRef.current.push(action);
    if (undoStackRef.current.length > 50) undoStackRef.current.shift();
    setUndoDepth(undoStackRef.current.length);
  }, []);

  const handleUndo = useCallback(async () => {
    const action = undoStackRef.current.pop();
    setUndoDepth(undoStackRef.current.length);
    if (!action) return;
    try {
      await action.run();
      // Let an open card re-seed its fields from the now-reverted task.
      setUndoNonce((n) => n + 1);
    } catch (err) {
      setLoadError((err as Error).message);
    }
  }, []);

  // Cmd/Ctrl+Z anywhere (except while typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.key.toLowerCase() !== "z") return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      e.preventDefault();
      handleUndo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleUndo]);

  // --- task handlers ---
  const handleStatusChange = async (taskId: number, status: TaskStatus) => {
    const prev = tasks.find((t) => t.id === taskId)?.status;
    setTasks((cur) => cur.map((t) => (t.id === taskId ? { ...t, status } : t)));
    await api.updateTask(taskId, { status });
    if (prev && prev !== status) {
      pushUndo({
        label: "status change",
        run: async () => {
          setTasks((cur) => cur.map((t) => (t.id === taskId ? { ...t, status: prev } : t)));
          await api.updateTask(taskId, { status: prev });
        },
      });
    }
  };

  const handleEditTask = async (
    taskId: number,
    patch: { description?: string; owner?: string | null; deadline?: string | null; status?: TaskStatus }
  ) => {
    const before = tasks.find((t) => t.id === taskId);
    const updated = await api.updateTask(taskId, patch);
    setTasks((cur) => cur.map((t) => (t.id === taskId ? updated : t)));
    if (before) {
      const revert = {
        description: before.description,
        owner: before.owner,
        deadline: before.deadline,
        status: before.status,
      };
      pushUndo({
        label: "edit task",
        run: async () => {
          const reverted = await api.updateTask(taskId, revert);
          setTasks((cur) => cur.map((t) => (t.id === taskId ? reverted : t)));
        },
      });
    }
  };

  // Keep a task's subtask/attachment count badges in sync as they change inside the modal.
  const handleTaskMetaChange = useCallback((taskId: number, meta: Partial<TaskMeta>) => {
    setTasks((cur) => cur.map((t) => (t.id === taskId ? { ...t, ...meta } : t)));
  }, []);

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
    try {
      const snapshot = await api.deleteTask(taskId);
      pushUndo({
        label: "delete task",
        run: async () => {
          const restored = await api.restoreTask(snapshot);
          setTasks((cur) => (cur.some((t) => t.id === restored.id) ? cur : [restored, ...cur]));
        },
      });
    } catch (err) {
      setLoadError((err as Error).message);
      reloadTasks(); // delete failed — resync so the card isn't wrongly hidden
    }
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

  // Turn deadline reminders on/off for a single board (opt-in). Driven from Account settings,
  // where the user picks which of their projects should remind them.
  const handleToggleProjectReminder = async (projectId: number, enabled: boolean) => {
    setProjects((prev) => prev.map((p) => (p.id === projectId ? { ...p, notify_enabled: enabled } : p)));
    try {
      await api.updateProject(projectId, { notify_enabled: enabled });
    } catch (err) {
      // Roll back the optimistic flip on failure.
      setProjects((prev) => prev.map((p) => (p.id === projectId ? { ...p, notify_enabled: !enabled } : p)));
      setLoadError((err as Error).message);
    }
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

  const handleChangePassword = async (currentPassword: string, newPassword: string) => {
    await api.changePassword(currentPassword, newPassword);
  };

  const handleUpdateNotifications = async (notifyEmail: boolean, notifyDaysBefore: number) => {
    const updated = await api.updateNotificationSettings(notifyEmail, notifyDaysBefore);
    updateStoredUser(updated);
    setSession((cur) => (cur?.mode === "user" ? { mode: "user", user: updated } : cur));
  };

  const handleSendTestNotification = async () => {
    const { sent_tasks } = await api.sendTestNotification();
    return sent_tasks;
  };

  const handleDeleteAccount = async () => {
    await api.deleteAccount();
    setShowAccount(false);
    handleLogout();
  };

  if (!ready) {
    return <LoadingScreen slow={slow} />;
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
        onOpenAccount={() => setShowAccount(true)}
      />

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
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
                  <h2 className="font-display text-2xl font-bold tracking-tight text-slate-900">{selectedProject?.name}</h2>
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
                  className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-semibold text-slate-700 bg-white shadow-sm ring-1 ring-slate-200 transition hover:bg-slate-50 hover:text-slate-900"
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
                      className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-semibold text-slate-700 bg-white shadow-sm ring-1 ring-slate-200 transition hover:bg-slate-50 hover:text-slate-900"
                      title="Rename project"
                    >
                      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.879.506l-3.012.86a.5.5 0 01-.617-.617l.86-3.012a2 2 0 01.506-.879l8.5-8.5z" />
                      </svg>
                      Rename
                    </button>
                    <button
                      onClick={handleDeleteProject}
                      className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-semibold text-slate-700 bg-white shadow-sm ring-1 ring-slate-200 transition hover:bg-rose-50 hover:text-rose-600 hover:ring-rose-200"
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

              <div className="min-w-0 space-y-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
                  <div className="relative w-full sm:min-w-[200px] sm:flex-1">
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
                      className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-9 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
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

                  {/* Action controls: keep these on one tidy row (they share a line on mobile,
                      while the search box gets its own full-width row above). */}
                  <div className="flex flex-wrap items-center justify-between gap-2 sm:justify-normal">
                  {user && projects.length > 1 && (
                    <div className="flex shrink-0 rounded-lg bg-white p-1 text-sm font-medium ring-1 ring-slate-200 shadow-sm">
                      <button
                        onClick={() => setSearchAllProjects(false)}
                        className={`rounded-md px-3 py-1 transition ${
                          searchAllProjects ? "text-slate-500 hover:text-slate-700" : "bg-ink text-white shadow-sm"
                        }`}
                      >
                        This project
                      </button>
                      <button
                        onClick={() => setSearchAllProjects(true)}
                        className={`rounded-md px-3 py-1 transition ${
                          searchAllProjects ? "bg-ink text-white shadow-sm" : "text-slate-500 hover:text-slate-700"
                        }`}
                      >
                        All projects
                      </button>
                    </div>
                  )}
                  <div className="flex shrink-0 rounded-lg bg-white p-1 text-sm font-medium ring-1 ring-slate-200 shadow-sm">
                    <button
                      onClick={() => setView("board")}
                      className={`rounded-md px-3 py-1 transition ${
                        activeView === "board" ? "bg-ink text-white shadow-sm" : "text-slate-500 hover:text-slate-700"
                      }`}
                    >
                      Board
                    </button>
                    <button
                      onClick={() => setView("calendar")}
                      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 transition ${
                        activeView === "calendar" ? "bg-ink text-white shadow-sm" : "text-slate-500 hover:text-slate-700"
                      }`}
                    >
                      <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor">
                        <path d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v9a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zM4 8h12v7H4V8z" />
                      </svg>
                      Calendar
                    </button>
                  </div>
                  {canEdit && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleUndo}
                        disabled={undoDepth === 0}
                        title="Undo (⌘Z / Ctrl+Z)"
                        aria-label="Undo"
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                      >
                        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                          <path d="M8 5V2.5a.5.5 0 00-.82-.38l-4.5 3.75a.5.5 0 000 .76l4.5 3.75A.5.5 0 008 10V7.5h3.5a4 4 0 110 8H7a1 1 0 100 2h4.5a6 6 0 100-12H8z" />
                        </svg>
                        <span className="hidden sm:inline">Undo</span>
                      </button>
                      <button
                        onClick={() => setCreatingTask(true)}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-ink px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700"
                      >
                        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                          <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
                        </svg>
                        Add task
                      </button>
                    </div>
                  )}
                  </div>
                </div>

                {owners.length > 0 && (
                  <Filters
                    owners={owners}
                    selectedOwner={selectedOwner}
                    onOwnerChange={setSelectedOwner}
                    sortByDeadline={sortByDeadline}
                    onSortToggle={() => setSortByDeadline((v) => !v)}
                    showSort={activeView === "board"}
                  />
                )}

                {activeView === "calendar" ? (
                  <CalendarView
                    tasks={visibleTasks}
                    canEdit={!!canEdit}
                    onEditTask={(t) => setEditingTaskId(t.id)}
                    onDeleteTask={handleDelete}
                    onReschedule={(taskId, deadline) => handleEditTask(taskId, { deadline })}
                  />
                ) : search.trim() && visibleTasks.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-200 bg-white/60 px-4 py-12 text-center text-sm text-slate-500">
                    No tasks match <span className="font-medium text-slate-700">“{search.trim()}”</span>.
                  </div>
                ) : (
                  <KanbanBoard
                    tasks={visibleTasks}
                    projectNames={searchAllProjects ? projectNames : undefined}
                    canEdit={!!canEdit}
                    onStatusChange={handleStatusChange}
                    onEdit={(t) => setEditingTaskId(t.id)}
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
        canEdit={!!canEdit}
        canUndo={undoDepth > 0}
        syncNonce={undoNonce}
        onUndo={handleUndo}
        onPushUndo={pushUndo}
        subtaskReloadNonce={subtaskReloadNonce}
        onRequestSubtaskReload={() => setSubtaskReloadNonce((n) => n + 1)}
        onClose={() => {
          setEditingTaskId(null);
          setCreatingTask(false);
        }}
        onSave={handleEditTask}
        onCreate={handleCreateTask}
        onMetaChange={handleTaskMetaChange}
      />

      <ShareModal project={shareProject} onClose={() => setShareProject(null)} />

      {user && (
        <AccountModal
          open={showAccount}
          user={user}
          reminderProjects={projects.filter((p) => p.owner_user_id === user.id)}
          onToggleProjectReminder={handleToggleProjectReminder}
          onClose={() => setShowAccount(false)}
          onChangePassword={handleChangePassword}
          onDeleteAccount={handleDeleteAccount}
          onUpdateNotifications={handleUpdateNotifications}
          onSendTestNotification={handleSendTestNotification}
        />
      )}
    </div>
  );
}

function LoadingScreen({ slow }: { slow: boolean }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5 px-6 text-center">
      <div className="relative flex items-center justify-center">
        <span className="absolute h-16 w-16 animate-ping rounded-full bg-slate-300/40" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/logo.png"
          alt="Meeting Orchestrator"
          className="relative h-14 w-14 rounded-full object-cover shadow-card"
        />
      </div>

      <div className="flex items-center gap-2 text-slate-600">
        <svg className="h-4 w-4 animate-spin text-slate-400" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
        <span className="text-sm font-medium">Loading your boards…</span>
      </div>

      {slow && (
        <p className="max-w-sm text-xs leading-relaxed text-slate-400">
          Waking up the server — the free hosting tier sleeps after inactivity, so the first load
          can take up to a minute.
        </p>
      )}
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
        className="mt-5 inline-flex items-center gap-1.5 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700"
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
        </svg>
        Create your first project
      </button>
    </div>
  );
}
