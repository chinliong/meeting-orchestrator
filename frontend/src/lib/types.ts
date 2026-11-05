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

/** Whether the signed-in user gets reminders for a board shared with them. */
export interface ReminderSubscriptionState {
  subscribed: boolean;
  /** Their account-wide reminders switch, which asking for a board's reminders turns on. */
  notify_email: boolean;
}

/** Someone who asked for a board's reminders, as the board's owner sees them. */
export interface Subscriber {
  user_id: number;
  email: string;
  /** The share link that gave them access. */
  via: "view" | "edit";
  created_at: string | null;
}

/** A board shared with the signed-in user whose reminders they get. */
export interface SharedReminder {
  project_id: number;
  project_name: string;
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
  // Date of the source meeting, so meetings that share a title stay distinguishable.
  meeting_date: string | null;
  description: string;
  owner: string | null;
  deadline: string | null;
  status: TaskStatus;
  // Null when there is no extraction score (tasks created by the project assistant).
  confidence: number | null;
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

/**
 * Snapshot returned when a task is deleted, enough to restore it with its subtasks (powers undo).
 * The server signs it, so it is sent back exactly as received. Attachments are not kept.
 */
export interface DeletedTask {
  task: Task;
  subtasks: { title: string; done: boolean; position: number }[];
  signature: string;
}

/** A reversible action on the undo stack. `run` performs the inverse of what just happened. */
export interface UndoAction {
  key?: string;
  label: string;
  run: () => void | Promise<void>;
}

export type MeetingStatus = "pending" | "processing" | "complete" | "failed";

/** A meeting as the board's meeting list shows it (GET /transcripts?project_id=). */
/** An AI overview of one meeting, written separately from the task extraction. */
export interface MeetingSummary {
  overview: string;
}

export interface MeetingListItem {
  id: number;
  project_id: number;
  title: string;
  meeting_date: string | null;
  status: MeetingStatus;
  error_message: string | null;
  /** Null until a summary has been written. */
  summary: MeetingSummary | null;
  /** True when the server tried to write the summary after extraction and could not. */
  summary_failed: boolean;
  /** When it was added, in UTC without a zone suffix (as the API sends it). */
  created_at: string | null;
  task_count: number;
}

export interface Meeting {
  id: number;
  project_id: number;
  title: string;
  status: MeetingStatus;
  error_message: string | null;
  /** Null until the server has written the meeting's summary, which it does after extraction. */
  summary: MeetingSummary | null;
  /** True when that attempt failed; the summary can still be written on request. */
  summary_failed: boolean;
  created_at: string;
  tasks: Task[];
}

export interface AgentReviewInput {
  title: string;
  meeting_date: string;
  transcript: string;
  instructions: string;
  check_duplicate?: boolean;
}

export type AgentTaskFields = Pick<Task, "description" | "owner" | "deadline" | "status">;

export interface AgentProposal {
  id: number;
  kind: "create" | "update";
  task_id: number | null;
  before: AgentTaskFields | null;
  after: AgentTaskFields;
  // An exact quote, except for a task the parser extracted, where it is the parser's source
  // decision (possibly paraphrased, possibly empty).
  evidence: string;
  reason: string;
  // Present only on tasks the parser extracted.
  confidence?: number | null;
  // A task the assistant matched to one already on the board; unticked unless the user adds it.
  possible_duplicate?: boolean;
  // id is null when the match is another task from the same meeting.
  duplicate_of?: { id: number | null; description: string };
}

export type AgentMutation = "apply" | "undo" | "refresh";

export interface AssistantImportResult {
  meeting_id: number;
  new_task_count: number;
  saved_review?: AgentReview;
  review: AgentReview | null;
  questions: string[];
}

export interface AgentReview {
  unavailable_proposal_ids?: number[];
  stale?: boolean;
  stale_reason?: string | null;
  id: string;
  mode: "meeting" | "chat" | "meeting_updates";
  status: "draft" | "applied" | "undone" | "dismissed";
  created_at: string;
  expires_at: string | null;
  input: AgentReviewInput;
  summary: string;
  questions: string[];
  proposals: AgentProposal[];
  model: string;
  steps: number;
  elapsed_seconds: number;
  trace: { label: string; tool: string }[];
  receipt: { proposal_ids: number[]; meeting_id: number | null; applied_at: string; reopened_as?: string } | null;
  /** On a review reopened after an undo: the changes chosen the first time. */
  preselected?: number[];
  /** The meeting's current title (it may have been renamed since), else the one it was added with. */
  title?: string;
}

export interface AgentReviewListItem {
  stale?: boolean;
  stale_reason?: string | null;
  id: string;
  mode: AgentReview["mode"];
  /** Meeting title, or the first changed task for chat edits. */
  title: string;
  status: AgentReview["status"];
  change_count: number;
  /** Possible duplicates in a pending review; not counted as suggested changes. */
  possible_duplicates?: number;
  created_at: string;
}

export interface AssistantSource {
  kind: "task" | "meeting";
  id: number;
  title: string;
  quote: string;
  owner: string | null;
  status: TaskStatus | null;
  deadline: string | null;
  meeting_date: string | null;
}

export interface AssistantAnswer {
  answer: string;
  sources: AssistantSource[];
  questions: string[];
  next_action: "none" | "review_meeting";
  review: AgentReview | null;
  model: string;
  trace: { label: string; tool: string }[];
  elapsed_seconds: number;
}

export interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
}
