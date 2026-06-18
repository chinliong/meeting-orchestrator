import type { AuthResponse, Meeting, Project, Task, TaskStatus, User } from "./types";

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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  if (workspaceToken) headers["X-Workspace-Token"] = workspaceToken;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${options?.method ?? "GET"} ${path} failed (${res.status}): ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
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

  // --- projects ---
  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string, description = "") =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  getProjectByToken: (token: string) =>
    request<Project>(`/projects/by-token/${encodeURIComponent(token)}`),

  updateProject: (id: number, patch: { name?: string; description?: string }) =>
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

  deleteTask: (id: number) => request<void>(`/tasks/${id}`, { method: "DELETE" }),

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
    const res = await fetch(`${API_BASE}/transcripts/audio`, { method: "POST", body: form, headers });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`POST /transcripts/audio failed (${res.status}): ${body}`);
    }
    return res.json();
  },
};
