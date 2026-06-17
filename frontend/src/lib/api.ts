import type { Meeting, Project, Task, TaskStatus } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${options?.method ?? "GET"} ${path} failed (${res.status}): ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string, description = "") =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),

  listTasks: (params: { projectId?: number; owner?: string; status?: TaskStatus } = {}) => {
    const qs = new URLSearchParams();
    if (params.projectId) qs.set("project_id", String(params.projectId));
    if (params.owner) qs.set("owner", params.owner);
    if (params.status) qs.set("status", params.status);
    const query = qs.toString();
    return request<Task[]>(`/tasks${query ? `?${query}` : ""}`);
  },

  updateTask: (id: number, patch: Partial<Pick<Task, "status" | "owner" | "deadline" | "description">>) =>
    request<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  deleteTask: (id: number) => request<void>(`/tasks/${id}`, { method: "DELETE" }),

  submitTranscript: (projectId: number, title: string, transcriptText: string) =>
    request<Meeting>("/transcripts", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, title, transcript_text: transcriptText }),
    }),

  submitAudio: async (projectId: number, title: string, file: File): Promise<Meeting> => {
    const form = new FormData();
    form.set("project_id", String(projectId));
    form.set("title", title);
    form.set("file", file);
    // Note: no Content-Type header — the browser sets the multipart boundary itself.
    const res = await fetch(`${API_BASE}/transcripts/audio`, { method: "POST", body: form });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`POST /transcripts/audio failed (${res.status}): ${body}`);
    }
    return res.json();
  },
};
