import type { AuthResponse, DeletedTask, Meeting, Project, Task, TaskStatus, User } from "./types";

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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  if (workspaceToken) headers["X-Workspace-Token"] = workspaceToken;

  const res = await fetchWithRetry(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${options?.method ?? "GET"} ${path} failed (${res.status}): ${body}`);
  }
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
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
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

  updateProject: (id: number, patch: { name?: string; description?: string; notify_muted?: boolean }) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

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

  // --- transcripts ---
  submitTranscript: (projectId: number, title: string, transcriptText: string) =>
    request<Meeting>("/transcripts", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, title, transcript_text: transcriptText }),
    }),

  getMeeting: (id: number) => request<Meeting>(`/transcripts/${id}`),

  updateMeeting: (id: number, title: string) =>
    request<Meeting>(`/transcripts/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),

  submitAudio: async (projectId: number, title: string, file: File): Promise<Meeting> => {
    const form = new FormData();
    form.set("project_id", String(projectId));
    form.set("title", title);
    form.set("file", file);
    // Note: no Content-Type header — the browser sets the multipart boundary itself.
    const headers: Record<string, string> = {};
    if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
    if (workspaceToken) headers["X-Workspace-Token"] = workspaceToken;
    const res = await fetchWithRetry(`${API_BASE}/transcripts/audio`, { method: "POST", body: form, headers });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`POST /transcripts/audio failed (${res.status}): ${body}`);
    }
    return res.json();
  },
};
