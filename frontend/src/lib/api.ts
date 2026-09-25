import type {
  Attachment,
  AuthResponse,
  DeletedTask,
  Meeting,
  MeetingListItem,
  MeetingSummary,
  Project,
  ReminderSubscriptionState,
  SharedReminder,
  Subscriber,
  Subtask,
  Task,
  TaskStatus,
  User,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1";

// Set by the app: the logged-in user's bearer token, and the share/capability token for
// whichever board is currently active. Either (or both) is attached to every request.
let authToken: string | null = null;
let workspaceToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function setWorkspaceToken(token: string | null) {
  workspaceToken = token;
}

/** An HTTP error from the API, carrying the status so callers can tell a 401 from the rest. */
export class ApiError extends Error {
  constructor(message: string, public status: number, public body = "") {
    super(message);
  }
}

// Called when a signed-in request comes back 401, meaning the login has expired or the account
// is gone. The app registers a handler that signs the user out.
let onSessionExpired: (() => void) | null = null;

export function setSessionExpiredHandler(handler: (() => void) | null) {
  onSessionExpired = handler;
}

// A wrong password on these routes is also a 401, so it must not end the session.
const PASSWORD_ROUTES = ["/auth/login", "/auth/signup", "/auth/password"];

async function throwIfFailed(res: Response, method: string, path: string): Promise<void> {
  if (res.ok) return;
  const body = await res.text();
  if (res.status === 401 && authToken && !PASSWORD_ROUTES.includes(path)) onSessionExpired?.();
  throw new ApiError(`${method} ${path} failed (${res.status}): ${body}`, res.status, body);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Render's free tier sleeps after inactivity. The first request that wakes it is answered by
// Render's boot proxy, not our app — a response with no CORS headers, which the browser surfaces
// as a "Failed to fetch" TypeError. That throw happens before the request reaches the server, so
// retrying is safe (nothing ran server-side). We retry ONLY these network throws — an actual HTTP
// response (e.g. 401) is returned to the caller untouched and fails immediately upstream.
async function fetchWithRetry(url: string, init: RequestInit, maxAttempts = 5): Promise<Response> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await fetch(url, init);
    } catch (err) {
      if (attempt >= maxAttempts) throw err;
      await sleep(2000);
    }
  }
}

// Auth/workspace headers without a JSON Content-Type — for multipart uploads and binary
// downloads, where the browser must set (or omit) Content-Type itself.
function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  if (workspaceToken) headers["X-Workspace-Token"] = workspaceToken;
  return headers;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  // A caller may pin a specific board's token (see getMeeting); otherwise use the active board's.
  if (workspaceToken && !headers["X-Workspace-Token"]) headers["X-Workspace-Token"] = workspaceToken;

  const res = await fetchWithRetry(`${API_BASE}${path}`, { ...options, headers });
  await throwIfFailed(res, options?.method ?? "GET", path);
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  // --- system ---
  health: () => request<{ status: string }>("/health"),

  // --- auth ---
  signup: (email: string, password: string, claimTokens: string[] = []) =>
    request<AuthResponse>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, claim_tokens: claimTokens }),
    }),
  login: (email: string, password: string, claimTokens: string[] = []) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, claim_tokens: claimTokens }),
    }),
  me: () => request<User>("/auth/me"),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>("/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  deleteAccount: () => request<void>("/auth/me", { method: "DELETE" }),
  updateNotificationSettings: (notifyEmail: boolean, notifyDaysBefore: number) =>
    request<User>("/auth/notifications", {
      method: "PATCH",
      body: JSON.stringify({ notify_email: notifyEmail, notify_days_before: notifyDaysBefore }),
    }),
  sendTestNotification: () =>
    request<{ sent_tasks: number }>("/auth/notifications/test", { method: "POST" }),
  forgotPassword: (email: string) =>
    request<void>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  resetPassword: (email: string, code: string, newPassword: string) =>
    request<void>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ email, code, new_password: newPassword }),
    }),

  // --- projects ---
  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string, description = "") =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  getProjectByToken: (token: string) =>
    request<Project>(`/projects/by-token/${encodeURIComponent(token)}`),

  updateProject: (id: number, patch: { name?: string; description?: string; notify_enabled?: boolean }) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  // Regenerate a share link, invalidating the old one. Owner-only on the server.
  rotateProjectToken: (id: number, which: "view" | "edit") =>
    request<Project>(`/projects/${id}/rotate-token?which=${which}`, { method: "POST" }),

  deleteProject: (id: number) => request<void>(`/projects/${id}`, { method: "DELETE" }),

  // --- tasks ---
  listTasks: (params: { projectId?: number; owner?: string; status?: TaskStatus } = {}) => {
    const qs = new URLSearchParams();
    if (params.projectId) qs.set("project_id", String(params.projectId));
    if (params.owner) qs.set("owner", params.owner);
    if (params.status) qs.set("status", params.status);
    const query = qs.toString();
    return request<Task[]>(`/tasks${query ? `?${query}` : ""}`);
  },

  createTask: (input: {
    projectId: number;
    description: string;
    owner?: string | null;
    deadline?: string | null;
    status?: TaskStatus;
  }) =>
    request<Task>("/tasks", {
      method: "POST",
      body: JSON.stringify({
        project_id: input.projectId,
        description: input.description,
        owner: input.owner ?? null,
        deadline: input.deadline ?? null,
        status: input.status ?? "todo",
      }),
    }),

  updateTask: (id: number, patch: Partial<Pick<Task, "status" | "owner" | "deadline" | "description">>) =>
    request<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  // Returns a snapshot of what was removed, so the caller can offer an undo.
  deleteTask: (id: number) => request<DeletedTask>(`/tasks/${id}`, { method: "DELETE" }),

  restoreTask: (snapshot: DeletedTask) =>
    request<Task>("/tasks/restore", { method: "POST", body: JSON.stringify(snapshot) }),

  // --- subtasks ---
  listSubtasks: (taskId: number) => request<Subtask[]>(`/tasks/${taskId}/subtasks`),

  createSubtask: (taskId: number, title: string) =>
    request<Subtask>(`/tasks/${taskId}/subtasks`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),

  // Have the LLM break the task down; the new subtasks are persisted and returned.
  generateSubtasks: (taskId: number, instructions?: string) =>
    request<Subtask[]>(`/tasks/${taskId}/subtasks/generate`, {
      method: "POST",
      body: JSON.stringify({ instructions: instructions ?? null }),
    }),

  updateSubtask: (id: number, patch: { title?: string; done?: boolean }) =>
    request<Subtask>(`/subtasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  deleteSubtask: (id: number) => request<void>(`/subtasks/${id}`, { method: "DELETE" }),

  // --- attachments ---
  listAttachments: (taskId: number) => request<Attachment[]>(`/tasks/${taskId}/attachments`),

  uploadAttachment: async (taskId: number, file: File): Promise<Attachment> => {
    const form = new FormData();
    form.set("file", file);
    // No Content-Type header — the browser sets the multipart boundary itself.
    const res = await fetchWithRetry(`${API_BASE}/tasks/${taskId}/attachments`, {
      method: "POST",
      body: form,
      headers: authHeaders(),
    });
    await throwIfFailed(res, "POST", `/tasks/${taskId}/attachments`);
    return res.json();
  },

  deleteAttachment: (id: number) => request<void>(`/attachments/${id}`, { method: "DELETE" }),

  // The file is access-controlled, so it can't be a plain <a href>: fetch it with the auth
  // headers, then hand the browser a blob URL to save under the original filename.
  downloadAttachment: async (id: number, filename: string): Promise<void> => {
    const res = await fetchWithRetry(`${API_BASE}/attachments/${id}`, {
      method: "GET",
      headers: authHeaders(),
    });
    await throwIfFailed(res, "GET", `/attachments/${id}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // --- transcripts ---
  // With `checkDuplicate`, a transcript already on this board is refused (409) so the user can
  // be asked before its tasks are added a second time.
  submitTranscript: (
    projectId: number,
    title: string,
    transcriptText: string,
    meetingDate: string,
    checkDuplicate = false
  ) =>
    request<Meeting>("/transcripts", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        title,
        transcript_text: transcriptText,
        // Relative deadline cues ("by Friday") resolve against this date, not the upload date.
        meeting_date: meetingDate || null,
        check_duplicate: checkDuplicate,
      }),
    }),

  // The board's meetings, newest first. `boardToken` pins that board's token, as for getMeeting.
  listMeetings: (projectId: number, boardToken?: string) =>
    request<MeetingListItem[]>(
      `/transcripts?project_id=${projectId}`,
      boardToken ? { headers: { "X-Workspace-Token": boardToken } } : undefined
    ),

  // Deletes the meeting with every task extracted from it.
  deleteMeeting: (id: number) => request<void>(`/transcripts/${id}`, { method: "DELETE" }),

  // --- reminders for people a board is shared with ---
  // `boardToken` pins the board's own share link, which is what gives a collaborator access.
  getMyReminders: (projectId: number, boardToken?: string) =>
    request<ReminderSubscriptionState>(
      `/projects/${projectId}/reminders/me`,
      boardToken ? { headers: { "X-Workspace-Token": boardToken } } : undefined
    ),
  subscribeReminders: (projectId: number, boardToken?: string) =>
    request<ReminderSubscriptionState>(`/projects/${projectId}/reminders/me`, {
      method: "PUT",
      ...(boardToken ? { headers: { "X-Workspace-Token": boardToken } } : {}),
    }),
  unsubscribeReminders: (projectId: number) =>
    request<void>(`/projects/${projectId}/reminders/me`, { method: "DELETE" }),
  listSharedReminders: () => request<SharedReminder[]>("/auth/reminder-subscriptions"),
  // Owner-only: who gets this board's reminders, and removing one of them.
  listSubscribers: (projectId: number) => request<Subscriber[]>(`/projects/${projectId}/subscribers`),
  removeSubscriber: (projectId: number, userId: number) =>
    request<void>(`/projects/${projectId}/subscribers/${userId}`, { method: "DELETE" }),

  // Writes (or rewrites) the meeting's AI summary. `boardToken` pins the meeting's own board, as
  // the summary can arrive after the user has switched to another.
  summariseMeeting: (id: number, boardToken?: string) =>
    request<MeetingSummary>(`/transcripts/${id}/summary`, {
      method: "POST",
      ...(boardToken ? { headers: { "X-Workspace-Token": boardToken } } : {}),
    }),

  // `boardToken` pins the token of the board the meeting belongs to, so polling a recording keeps
  // working after the user switches to another board.
  getMeeting: (id: number, boardToken?: string) =>
    request<Meeting>(`/transcripts/${id}`, boardToken ? { headers: { "X-Workspace-Token": boardToken } } : undefined),

  updateMeeting: (id: number, title: string) =>
    request<Meeting>(`/transcripts/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),

  submitAudio: async (projectId: number, title: string, file: File, meetingDate: string): Promise<Meeting> => {
    const form = new FormData();
    form.set("project_id", String(projectId));
    form.set("title", title);
    form.set("meeting_date", meetingDate);
    form.set("file", file);
    // Note: no Content-Type header — the browser sets the multipart boundary itself.
    const headers: Record<string, string> = {};
    if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
    if (workspaceToken) headers["X-Workspace-Token"] = workspaceToken;
    const res = await fetchWithRetry(`${API_BASE}/transcripts/audio`, { method: "POST", body: form, headers });
    await throwIfFailed(res, "POST", "/transcripts/audio");
    return res.json();
  },
};
