export type TaskStatus = "todo" | "in_progress" | "done";

export type AccessLevel = "edit" | "view";

export interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
  owner_user_id: number | null;
  notify_enabled: boolean;
  access_level: AccessLevel;
  view_token: string;
  edit_token: string | null; // present only when you have edit access
}

export interface User {
  id: number;
  email: string;
  created_at: string;
  notify_email: boolean;
  notify_days_before: number;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface Task {
  id: number;
  project_id: number;
  meeting_id: number | null;
  meeting_title: string | null;
  description: string;
  owner: string | null;
  deadline: string | null;
  status: TaskStatus;
  confidence: number;
  source_decision: string | null;
  created_at: string;
  // Rollup counts so cards can show progress without fetching the children.
  subtask_total: number;
  subtask_done: number;
  attachment_count: number;
}

/** Per-task rollup counts, kept in sync as subtasks/attachments change in the editor. */
export interface TaskMeta {
  subtask_total: number;
  subtask_done: number;
  attachment_count: number;
}

export interface Subtask {
  id: number;
  task_id: number;
  title: string;
  done: boolean;
  position: number;
}

export interface Attachment {
  id: number;
  task_id: number;
  filename: string;
  content_type: string;
  size: number;
  created_at: string;
}

/** Snapshot returned when a task is deleted, enough to restore it (powers undo). */
export interface DeletedTask {
  task: Task;
}

/** A reversible action on the undo stack. `run` performs the inverse of what just happened. */
export interface UndoAction {
  label: string;
  run: () => void | Promise<void>;
}

export type MeetingStatus = "pending" | "processing" | "complete" | "failed";

export interface Meeting {
  id: number;
  project_id: number;
  title: string;
  status: MeetingStatus;
  error_message: string | null;
  created_at: string;
  tasks: Task[];
}
