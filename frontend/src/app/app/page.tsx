"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import AccountModal from "@/components/AccountModal";
import AuthGate from "@/components/AuthGate";
import CalendarView from "@/components/CalendarView";
import EditTaskModal from "@/components/EditTaskModal";
import Filters from "@/components/Filters";
import KanbanBoard from "@/components/KanbanBoard";
import MeetingFilter from "@/components/MeetingFilter";
import MeetingSummaryCard from "@/components/MeetingSummaryCard";
import ConfirmDialog from "@/components/ConfirmDialog";
import ProjectModal from "@/components/ProjectModal";
import type { ProjectScope } from "@/components/ProjectPicker";
import ShareModal from "@/components/ShareModal";
import StatsBar from "@/components/StatsBar";
import TopBar from "@/components/TopBar";
import TranscriptUpload from "@/components/TranscriptUpload";
import { ApiError, api, setAuthToken, setSessionExpiredHandler, setWorkspaceToken } from "@/lib/api";
import { formatAddedAt } from "@/lib/format";
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
import type {
  AuthResponse,
  Meeting,
  MeetingListItem,
  MeetingSummary,
  Project,
  Task,
  TaskMeta,
  TaskStatus,
  UndoAction,
  User,
} from "@/lib/types";

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
  // Which boards the cross-board view includes; null means all of the user's boards.
  const [boardScope, setBoardScope] = useState<number[] | null>(null);
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
  // The board's meeting list reloads whenever this changes (a meeting added, finished or deleted).
  const [meetingsKey, setMeetingsKey] = useState(0);
  // The meeting just added here: its row and its tasks are marked "New" until the board changes.
  const [latestMeetingId, setLatestMeetingId] = useState<number | null>(null);
  // The board's meetings (for the Meeting filter), and the one the board is filtered to.
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState<number | null>(null);
  // Meeting summaries: the meeting whose summary is shown after it was just added (until hidden),
  // summaries written in this session (newer than the loaded list), and those being written or
  // that failed, each by meeting id.
  const [summaryShownFor, setSummaryShownFor] = useState<number | null>(null);
  const [freshSummaries, setFreshSummaries] = useState<Record<number, MeetingSummary>>({});
  const [summarising, setSummarising] = useState<Record<number, true>>({});
  const [summaryErrors, setSummaryErrors] = useState<Record<number, string>>({});
  // The Delete meeting confirmation, and the "add this transcript again?" question.
  const [meetingDeletion, setMeetingDeletion] = useState<{ meeting: MeetingListItem; busy: boolean; error: string | null } | null>(null);
  const [duplicatePrompt, setDuplicatePrompt] = useState<{
    title: string;
    createdAt: string | null;
    resolve: (addAgain: boolean) => void;
  } | null>(null);
  // The Delete project confirmation: null while closed.
  const [projectDeletion, setProjectDeletion] = useState<{ busy: boolean; error: string | null } | null>(null);

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
          if (err instanceof ApiError && err.status === 401) {
            // The stored login has expired (or the account was deleted): sign out and show the
            // sign-in screen, rather than a signed-in view whose every request fails.
            clearAuth();
            setAuthToken(null);
            sess = wToken ? { mode: "guest" } : null;
            setSession(sess);
          } else {
            setLoadError((err as Error).message);
          }
        }
      }
      if (sess?.mode === "guest") {
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
  // Several projects at once is for reviewing: the cards stay editable (they are the user's own
  // boards), but adding a meeting or task needs one project, so capture shows for one only.
  const cardsEditable = searchAllProjects || !!canEdit;
  const showCapture = !searchAllProjects && !!canEdit;

  // The task the card is editing, resolved live from state so edits/undo are reflected.
  const editingTask = editingTaskId != null ? tasks.find((t) => t.id === editingTaskId) ?? null : null;

  // The cross-board view covers the boards the user owns (the API returns only those).
  const ownedProjects = useMemo(
    () => (user ? projects.filter((p) => p.owner_user_id === user.id) : []),
    [projects, user]
  );

  const shownProjects = useMemo(
    () => (boardScope ? ownedProjects.filter((p) => boardScope.includes(p.id)) : ownedProjects),
    [ownedProjects, boardScope]
  );
  const viewTitle =
    boardScope && shownProjects.length < ownedProjects.length
      ? `${shownProjects.length} project${shownProjects.length === 1 ? "" : "s"}`
      : "All projects";
  // Which projects are shown, kept to one short line however many there are: all of them are
  // summarised by count, and a long chosen list names the first two and counts the rest.
  const shownNames = shownProjects.map((p) => p.name);
  const viewSummary =
    viewTitle === "All projects"
      ? `all ${ownedProjects.length} of your projects`
      : shownNames.length <= 3
        ? shownNames.length === 1
          ? shownNames[0]
          : `${shownNames.slice(0, -1).join(", ")} and ${shownNames[shownNames.length - 1]}`
        : `${shownNames.slice(0, 2).join(", ")} and ${shownNames.length - 2} more projects`;

  const handleSelectProject = (id: number) => {
    setSearchAllProjects(false);
    setSelectedProjectId(id);
  };

  // The multi-project view lives in the project picker, for signed-in owners of 2+ boards.
  const projectScope: ProjectScope | undefined =
    user && ownedProjects.length > 1
      ? {
          ownedIds: ownedProjects.map((p) => p.id),
          active: searchAllProjects,
          selected: boardScope,
          onShowAll: () => {
            setBoardScope(null);
            setSearchAllProjects(true);
          },
          onShowSome: (ids) => {
            setBoardScope(ids);
            setSearchAllProjects(true);
          },
        }
      : undefined;

  const projectNames = useMemo(
    () => new Map(projects.map((p) => [p.id, p.name])),
    [projects]
  );

  // Numbers each task load, so a slow response for a board the user has since left cannot
  // overwrite the tasks of the board they are now looking at.
  const loadSeqRef = useRef(0);

  // Set the active board's capability token, then (re)load its tasks.
  const reloadTasks = useCallback(() => {
    const seq = ++loadSeqRef.current;
    const apply = (list: Task[]) => {
      if (seq === loadSeqRef.current) setTasks(list);
    };
    const fail = (err: Error) => {
      if (seq === loadSeqRef.current) setLoadError(err.message);
    };
    if (searchAllProjects && session?.mode === "user") {
      setWorkspaceToken(null);
      api
        .listTasks({})
        .then((list) => apply(boardScope ? list.filter((t) => boardScope.includes(t.project_id)) : list))
        .catch(fail);
      return;
    }
    const proj = projects.find((p) => p.id === selectedProjectId) ?? null;
    setWorkspaceToken(proj ? workspaceTokenFor(proj) : null);
    if (selectedProjectId) {
      api.listTasks({ projectId: selectedProjectId }).then(apply).catch(fail);
    } else {
      setTasks([]);
    }
  }, [selectedProjectId, searchAllProjects, boardScope, projects, session]);

  // What is on screen: one board, all boards, or a chosen set. The owner filter and undo history
  // below reset whenever it changes.
  const viewKey = searchAllProjects ? (boardScope ? boardScope.join(",") : "all") : `board:${selectedProjectId}`;

  // The latest reloadTasks. A transcript or recording can take minutes to process, and the user
  // may switch boards meanwhile; reloading through this ref refreshes the board now on screen,
  // not the one that was open when the upload started.
  const reloadTasksRef = useRef(reloadTasks);
  reloadTasksRef.current = reloadTasks;

  useEffect(() => {
    if (ready) reloadTasks();
  }, [ready, reloadTasks]);

  // A board's owner filter does not carry over to another board, where it could hide every task.
  useEffect(() => {
    setSelectedOwner("");
    setLatestMeetingId(null);
    setSelectedMeetingId(null);
    setSummaryShownFor(null);
  }, [viewKey]);

  // A board selection belongs to the account that made it.
  useEffect(() => {
    setBoardScope(null);
    setSearchAllProjects(false);
  }, [user?.id]);

  // The board's meetings, for the Meeting filter: one project at a time, reloaded whenever a
  // meeting is added, finishes processing, is renamed or is deleted (meetingsKey). The board's own
  // token is passed explicitly so the list loads for this board even mid-switch.
  const meetingsBoardId = !searchAllProjects && selectedProject ? selectedProject.id : null;
  const meetingsBoardToken = selectedProject ? workspaceTokenFor(selectedProject) : undefined;
  useEffect(() => {
    if (!ready || meetingsBoardId === null) {
      setMeetings([]);
      return;
    }
    let cancelled = false;
    api
      .listMeetings(meetingsBoardId, meetingsBoardToken)
      .then((list) => !cancelled && setMeetings(list))
      .catch(() => !cancelled && setMeetings([]));
    return () => {
      cancelled = true;
    };
  }, [ready, meetingsBoardId, meetingsBoardToken, meetingsKey]);
  const meetingFilterShown = meetingsBoardId !== null && meetings.length > 0;

  // Writes a meeting's summary with a separate request after its tasks are saved, so a slow or
  // failed summary never holds up or affects the tasks. `boardToken` pins the meeting's board.
  const requestSummary = useCallback(async (meetingId: number, boardToken?: string) => {
    setSummarising((cur) => ({ ...cur, [meetingId]: true }));
    setSummaryErrors(({ [meetingId]: _cleared, ...rest }) => rest);
    try {
      const summary = await api.summariseMeeting(meetingId, boardToken);
      setFreshSummaries((cur) => ({ ...cur, [meetingId]: summary }));
    } catch {
      setSummaryErrors((cur) => ({ ...cur, [meetingId]: "Couldn't write a summary right now. Please try again." }));
    } finally {
      setSummarising(({ [meetingId]: _done, ...rest }) => rest);
    }
  }, []);
  // The card shows the meeting chosen in the Meeting filter, or else the one just added, or else a
  // board's only meeting (whose tasks are the whole board).
  const onlyMeetingId = meetings.length === 1 ? meetings[0].id : null;
  const summaryMeeting =
    meetings.find((m) => m.id === (selectedMeetingId ?? summaryShownFor ?? onlyMeetingId)) ?? null;
  // It can be hidden only when it is not the board's current view: not the chosen meeting, nor the only one.
  const summaryHideable =
    summaryMeeting !== null && summaryMeeting.id !== selectedMeetingId && summaryMeeting.id !== onlyMeetingId;
  // A viewer who cannot write a summary is not shown an empty one unless they chose that meeting.
  const summaryWorthShowing =
    summaryMeeting !== null &&
    (cardsEditable ||
      summaryMeeting.id === selectedMeetingId ||
      !!(freshSummaries[summaryMeeting.id] ?? summaryMeeting.summary));

  // The tasks of the meeting chosen in the Meeting filter (all tasks when none is chosen). The
  // owner filter lists only their owners, so it never offers a name with no tasks on screen.
  const meetingTasks = useMemo(
    () => (selectedMeetingId === null ? tasks : tasks.filter((t) => t.meeting_id === selectedMeetingId)),
    [tasks, selectedMeetingId]
  );
  const owners = useMemo(
    () => Array.from(new Set(meetingTasks.map((t) => t.owner).filter(Boolean))) as string[],
    [meetingTasks]
  );

  // The filter only applies while some task still has that owner (e.g. not after the owner's last
  // task is deleted or reassigned); otherwise it would hide every task with no way to clear it.
  const activeOwner = owners.includes(selectedOwner) ? selectedOwner : "";
  // Clear it for good, so it does not silently come back if that owner reappears (e.g. on undo).
  useEffect(() => {
    if (selectedOwner && !owners.includes(selectedOwner)) setSelectedOwner("");
  }, [owners, selectedOwner]);

  const visibleTasks = useMemo(() => {
    let result = activeOwner ? meetingTasks.filter((t) => t.owner === activeOwner) : meetingTasks;
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
  }, [meetingTasks, activeOwner, sortByDeadline, search]);

  // Calendar plots task deadlines; it works in any task view (single board or across all).
  const activeView: BoardView = view;

  // --- undo: a shared stack whose entries each perform the inverse of an action ---
  const undoStackRef = useRef<UndoAction[]>([]);
  const [undoDepth, setUndoDepth] = useState(0);
  // Bumped whenever the history is cleared. A handler notes it before its request, so an action
  // that finishes after the user has switched boards is not added to the new board's history.
  const undoGenRef = useRef(0);

  // Undo runs with the current board's credentials and updates the tasks on screen, so its
  // history is cleared on switching board or view, and on signing in or out.
  useEffect(() => {
    undoGenRef.current += 1;
    undoStackRef.current = [];
    setUndoDepth(0);
  }, [viewKey, session?.mode, user?.id]);

  const pushUndo = useCallback((action: UndoAction, gen?: number) => {
    if (gen !== undefined && gen !== undoGenRef.current) return;
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
    const gen = undoGenRef.current;
    setTasks((cur) => cur.map((t) => (t.id === taskId ? { ...t, status } : t)));
    try {
      await api.updateTask(taskId, { status });
    } catch (err) {
      // The save failed: move the card back to its column and say why.
      if (prev) setTasks((cur) => cur.map((t) => (t.id === taskId ? { ...t, status: prev } : t)));
      setLoadError((err as Error).message);
      return;
    }
    if (prev && prev !== status) {
      pushUndo({
        label: "status change",
        run: async () => {
          setTasks((cur) => cur.map((t) => (t.id === taskId ? { ...t, status: prev } : t)));
          await api.updateTask(taskId, { status: prev });
        },
      }, gen);
    }
  };

  const handleEditTask = async (
    taskId: number,
    patch: { description?: string; owner?: string | null; deadline?: string | null; status?: TaskStatus }
  ) => {
    const before = tasks.find((t) => t.id === taskId);
    const gen = undoGenRef.current;
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
      }, gen);
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
    setMeetingsKey((k) => k + 1);
    setTasks((prev) =>
      prev.map((t) => (t.meeting_id === meetingId ? { ...t, meeting_title: updated.title } : t))
    );
  };

  const handleDelete = async (taskId: number) => {
    const gen = undoGenRef.current;
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    try {
      const snapshot = await api.deleteTask(taskId);
      pushUndo({
        label: "delete task",
        run: async () => {
          const restored = await api.restoreTask(snapshot);
          setTasks((cur) => (cur.some((t) => t.id === restored.id) ? cur : [restored, ...cur]));
        },
      }, gen);
    } catch (err) {
      setLoadError((err as Error).message);
      reloadTasksRef.current(); // delete failed — resync so the card isn't wrongly hidden
    }
  };

  const handleTranscriptSubmit = async (title: string, transcriptText: string, meetingDate: string) => {
    if (!selectedProjectId) return;
    const projectId = selectedProjectId;
    const submit = (checkDuplicate: boolean) =>
      api.submitTranscript(projectId, title, transcriptText, meetingDate, checkDuplicate);
    let meeting: Meeting;
    try {
      meeting = await submit(true);
    } catch (err) {
      // The same transcript already on this board: ask before adding a second copy of its tasks.
      const earlier = duplicateOf(err);
      if (!earlier) throw err;
      const addAgain = await new Promise<boolean>((resolve) =>
        setDuplicatePrompt({ title: earlier.title, createdAt: earlier.created_at, resolve })
      );
      setDuplicatePrompt(null);
      if (!addAgain) throw new Error("Not added: this transcript is already on this board.");
      meeting = await submit(false);
    }
    setMeetingsKey((k) => k + 1);
    // A failed extraction still comes back as 201 with status "failed", so check it: throwing
    // keeps the pasted transcript in the form and shows the error instead of a silent no-op.
    if (meeting.status === "failed") {
      throw new Error(meeting.error_message || "The transcript could not be processed. Please try again.");
    }
    setLatestMeetingId(meeting.id);
    reloadTasksRef.current();
    const board = projects.find((p) => p.id === projectId);
    setSummaryShownFor(meeting.id);
    requestSummary(meeting.id, board ? workspaceTokenFor(board) : undefined);
  };

  const handleAudioSubmit = async (title: string, file: File, meetingDate: string) => {
    if (!selectedProjectId) return;
    // The board this recording belongs to, whose token the polling keeps using.
    const board = projects.find((p) => p.id === selectedProjectId);
    const boardToken = board ? workspaceTokenFor(board) : undefined;
    const meeting = await api.submitAudio(selectedProjectId, title, file, meetingDate);
    setMeetingsKey((k) => k + 1); // listed straight away, as "Processing…"
    // A long recording can take many minutes on the free server (converting the audio alone runs
    // for minutes). The job keeps going on the server whatever the browser does, so give up
    // waiting only after a generous limit, and then say so rather than invite a second upload.
    const deadline = Date.now() + 20 * 60 * 1000;
    let current = meeting;
    while (current.status === "processing" || current.status === "pending") {
      if (Date.now() > deadline) {
        throw new Error(
          "This recording is still being processed. Its tasks will be added to the board when it " +
            "finishes, so there is no need to upload it again. Refresh the page later to see them."
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 2500));
      try {
        current = await api.getMeeting(meeting.id, boardToken);
      } catch (err) {
        // A network error (e.g. the server restarting) is temporary: keep polling. An HTTP error
        // such as a 404 (the board was deleted) is final.
        if (err instanceof ApiError) throw err;
      }
    }
    setMeetingsKey((k) => k + 1);
    if (current.status === "failed") {
      throw new Error(current.error_message || "Transcription failed.");
    }
    setLatestMeetingId(meeting.id);
    reloadTasksRef.current();
    setSummaryShownFor(meeting.id);
    requestSummary(meeting.id, boardToken);
  };

  const performDeleteMeeting = async () => {
    if (!meetingDeletion) return;
    const { meeting } = meetingDeletion;
    setMeetingDeletion({ meeting, busy: true, error: null });
    try {
      await api.deleteMeeting(meeting.id);
    } catch (err) {
      const raw = (err as Error).message;
      setMeetingDeletion({ meeting, busy: false, error: raw.match(/"detail":"([^"]+)"/)?.[1] ?? raw });
      return;
    }
    setMeetingDeletion(null);
    if (latestMeetingId === meeting.id) setLatestMeetingId(null);
    if (selectedMeetingId === meeting.id) setSelectedMeetingId(null);
    if (summaryShownFor === meeting.id) setSummaryShownFor(null);
    // Undo entries may refer to the tasks just removed, so the history starts afresh.
    undoGenRef.current += 1;
    undoStackRef.current = [];
    setUndoDepth(0);
    setMeetingsKey((k) => k + 1);
    reloadTasksRef.current();
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

  // Regenerate one of a board's share links. Owner-only, so we only touch the owned
  // projects list — and keep the open share dialog in sync with the new token.
  const handleRotateToken = async (which: "view" | "edit") => {
    if (!shareProject) return;
    const updated = await api.rotateProjectToken(shareProject.id, which);
    setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    setShareProject(updated);
  };

  const handleDeleteProject = () => {
    if (selectedProjectId) setProjectDeletion({ busy: false, error: null });
  };

  const performDeleteProject = async () => {
    const id = selectedProjectId;
    if (!id) return;
    setProjectDeletion({ busy: true, error: null });
    try {
      await api.deleteProject(id);
    } catch (err) {
      // Keep the dialog open and say why, rather than failing silently.
      const raw = (err as Error).message;
      const detail = raw.match(/"detail":"([^"]+)"/)?.[1];
      setProjectDeletion({ busy: false, error: detail ?? raw });
      return;
    }
    setProjectDeletion(null);
    const remaining = projects.filter((p) => p.id !== id);
    setProjects(remaining);
    if (!user) removeGuestWorkspace(id);
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

  // A login that expires while the app is open signs the user out on their next request.
  useEffect(() => {
    if (!ready) return;
    setSessionExpiredHandler(() => {
      setShowAccount(false);
      handleLogout();
    });
    return () => setSessionExpiredHandler(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

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
        onSelectProject={handleSelectProject}
        scope={projectScope}
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
            <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-display text-[26px] font-bold tracking-tight text-slate-900">
                    {searchAllProjects ? viewTitle : selectedProject?.name}
                  </h2>
                  {!searchAllProjects && !canEdit && (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                      View only
                    </span>
                  )}
                </div>
                {searchAllProjects ? (
                  <p className="mt-0.5 text-[15px] text-slate-500" title={shownNames.join(", ")}>
                    Showing tasks from {viewSummary}. Pick a single project to add meetings or tasks.
                  </p>
                ) : (
                  selectedProject?.description && (
                    <p className="mt-0.5 text-[15px] text-slate-500">{selectedProject.description}</p>
                  )
                )}
              </div>
              {!searchAllProjects && (
              <div className="-ml-2.5 flex shrink-0 flex-wrap gap-0.5 sm:ml-0">
                <button
                  onClick={() => setShareProject(selectedProject)}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-900/5 hover:text-slate-900"
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
                      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-900/5 hover:text-slate-900"
                      title="Rename project"
                    >
                      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.879.506l-3.012.86a.5.5 0 01-.617-.617l.86-3.012a2 2 0 01.506-.879l8.5-8.5z" />
                      </svg>
                      Rename
                    </button>
                    <button
                      onClick={handleDeleteProject}
                      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-rose-50 hover:text-rose-600"
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
              )}
            </div>

            <div className="mb-6">
              <StatsBar tasks={tasks} />
            </div>

            <div className={showCapture ? "grid gap-6 lg:grid-cols-[340px_1fr]" : ""}>
              {showCapture && (
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
                      placeholder="Search tasks…"
                      className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-9 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
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
                  <div className="flex shrink-0 rounded-lg bg-slate-900/[0.05] p-1 text-sm font-medium">
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
                  {cardsEditable && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleUndo}
                        disabled={undoDepth === 0}
                        title="Undo (⌘Z / Ctrl+Z)"
                        aria-label="Undo"
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-900/5 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                      >
                        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                          <path d="M8 5V2.5a.5.5 0 00-.82-.38l-4.5 3.75a.5.5 0 000 .76l4.5 3.75A.5.5 0 008 10V7.5h3.5a4 4 0 110 8H7a1 1 0 100 2h4.5a6 6 0 100-12H8z" />
                        </svg>
                        <span className="hidden sm:inline">Undo</span>
                      </button>
                      {showCapture && (
                      <button
                        onClick={() => setCreatingTask(true)}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-ink px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700"
                      >
                        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                          <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
                        </svg>
                        Add task
                      </button>
                      )}
                    </div>
                  )}
                  </div>
                </div>

                {(owners.length > 0 || meetingFilterShown) && (
                  <Filters
                    owners={owners}
                    selectedOwner={activeOwner}
                    onOwnerChange={setSelectedOwner}
                    sortByDeadline={sortByDeadline}
                    onSortToggle={() => setSortByDeadline((v) => !v)}
                    showSort={activeView === "board"}
                    extra={
                      meetingFilterShown ? (
                        <MeetingFilter
                          meetings={meetings}
                          selectedMeetingId={selectedMeetingId}
                          onSelect={setSelectedMeetingId}
                          latestMeetingId={latestMeetingId}
                          canEdit={!!canEdit}
                          onDelete={(m) => setMeetingDeletion({ meeting: m, busy: false, error: null })}
                        />
                      ) : undefined
                    }
                  />
                )}

                {summaryMeeting && summaryMeeting.status !== "failed" && summaryWorthShowing && (
                  <MeetingSummaryCard
                    key={summaryMeeting.id}
                    meeting={summaryMeeting}
                    summary={freshSummaries[summaryMeeting.id] ?? summaryMeeting.summary}
                    working={!!summarising[summaryMeeting.id]}
                    error={summaryErrors[summaryMeeting.id] ?? null}
                    canEdit={cardsEditable}
                    onSummarise={() => requestSummary(summaryMeeting.id, meetingsBoardToken)}
                    onDismiss={summaryHideable ? () => setSummaryShownFor(null) : undefined}
                  />
                )}

                {activeView === "calendar" ? (
                  <CalendarView
                    tasks={visibleTasks}
                    canEdit={cardsEditable}
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
                    canEdit={cardsEditable}
                    onStatusChange={handleStatusChange}
                    onEdit={(t) => setEditingTaskId(t.id)}
                    onDelete={handleDelete}
                    onRenameMeeting={handleRenameMeeting}
                    newMeetingId={latestMeetingId}
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
        canEdit={cardsEditable}
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

      <ConfirmDialog
        open={meetingDeletion !== null}
        title={`Delete “${meetingDeletion?.meeting.title ?? ""}”?`}
        message={
          meetingDeletion && (
            <>
              {meetingDeletion.meeting.created_at && <>Added {formatAddedAt(meetingDeletion.meeting.created_at, true)}. </>}
              This removes the meeting and its {meetingDeletion.meeting.task_count} task
              {meetingDeletion.meeting.task_count === 1 ? "" : "s"}, with their subtasks and attachments. This
              can&apos;t be undone.
            </>
          )
        }
        confirmLabel="Delete meeting"
        tone="danger"
        busy={meetingDeletion?.busy}
        error={meetingDeletion?.error}
        onConfirm={performDeleteMeeting}
        onCancel={() => setMeetingDeletion(null)}
      />

      <ConfirmDialog
        open={duplicatePrompt !== null}
        title="Add this transcript again?"
        message={
          duplicatePrompt && (
            <>
              This exact transcript is already on this board as “{duplicatePrompt.title}”
              {duplicatePrompt.createdAt && <>, added {formatAddedAt(duplicatePrompt.createdAt)}</>}. Adding it
              again creates a second copy of its tasks.
            </>
          )
        }
        confirmLabel="Add again"
        onConfirm={() => duplicatePrompt?.resolve(true)}
        onCancel={() => duplicatePrompt?.resolve(false)}
      />

      <ConfirmDialog
        open={projectDeletion !== null}
        title={`Delete “${selectedProject?.name ?? "this project"}”?`}
        message={
          <>
            This removes the project and everything in it: {tasks.length} task{tasks.length === 1 ? "" : "s"}, with
            their meetings, subtasks and attachments. Anyone using its share links will lose access. This
            can&apos;t be undone.
          </>
        }
        confirmLabel="Delete project"
        tone="danger"
        busy={projectDeletion?.busy}
        error={projectDeletion?.error}
        onConfirm={performDeleteProject}
        onCancel={() => setProjectDeletion(null)}
      />

      <ShareModal
        project={shareProject}
        isOwner={!!user && !!shareProject && shareProject.owner_user_id === user.id}
        onRegenerate={handleRotateToken}
        onClose={() => setShareProject(null)}
      />

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

/** The earlier meeting, when a submit was refused as a duplicate transcript (409). */
function duplicateOf(err: unknown): { title: string; created_at: string | null } | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  try {
    const detail = JSON.parse(err.body).detail;
    return detail?.code === "duplicate_transcript" ? detail.meeting : null;
  } catch {
    return null;
  }
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
