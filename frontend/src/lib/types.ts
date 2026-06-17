export type TaskStatus = "todo" | "in_progress" | "done";

export interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface Task {
  id: number;
  project_id: number;
  meeting_id: number | null;
  description: string;
  owner: string | null;
  deadline: string | null;
  status: TaskStatus;
  confidence: number;
  source_decision: string | null;
  created_at: string;
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
