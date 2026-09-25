"use client";

import { useState } from "react";

import { formatMeetingDate } from "@/lib/format";
import type { MeetingListItem, MeetingSummary } from "@/lib/types";

interface Props {
  meeting: MeetingListItem;
  /** The meeting's summary, or null if none has been written yet. */
  summary: MeetingSummary | null;
  /** A summary is being written for this meeting right now. */
  working: boolean;
  /** Why the last attempt to write one failed, if it did. */
  error: string | null;
  canEdit: boolean;
  onSummarise: () => void;
  /** Hides the card; omitted when it belongs to the meeting chosen in the Meeting filter or the board's only meeting. */
  onDismiss?: () => void;
}

/**
 * A short AI overview of one meeting, shown above the board, so the tasks it produced have their
 * context. It describes the meeting as it happened (the board shows where the work stands now). It
 * is written by a separate request after the tasks are extracted and is labelled as AI-written,
 * since it is not part of the evaluated extraction.
 */
export default function MeetingSummaryCard({ meeting, summary, working, error, canEdit, onSummarise, onDismiss }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const processed = meeting.status === "complete";
  const date = meeting.meeting_date ? formatMeetingDate(meeting.meeting_date) : null;

  let body: React.ReactNode;
  if (working) {
    body = (
      <div aria-live="polite">
        <p className="text-sm text-slate-500">Writing a summary…</p>
        <div className="mt-2 space-y-2" aria-hidden>
          <div className="h-2.5 w-11/12 animate-pulse rounded-full bg-slate-100" />
          <div className="h-2.5 w-3/4 animate-pulse rounded-full bg-slate-100" />
        </div>
      </div>
    );
  } else if (!processed) {
    body = <p className="text-sm text-slate-500">A summary can be written once this meeting has been processed.</p>;
  } else if (summary) {
    body = (
      <>
        <p className="text-sm leading-relaxed text-slate-700">{summary.overview}</p>
        {error && <p className="mt-2 text-[13px] text-rose-600">{error}</p>}
        <p className="mt-2 text-[11.5px] text-slate-400">
          Written by AI from the transcript, as a summary of the meeting. The tasks on the board show where the work stands now.
        </p>
      </>
    );
  } else {
    body = (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={`text-sm ${error ? "text-rose-600" : "text-slate-500"}`}>
          {error ?? (canEdit ? "No summary yet for this meeting." : "No summary has been written for this meeting yet.")}
        </p>
        {canEdit && (
          <button
            type="button"
            onClick={onSummarise}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700"
          >
            <SparkIcon className="h-3.5 w-3.5" />
            {error ? "Try again" : "Summarise this meeting"}
          </button>
        )}
      </div>
    );
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm" aria-label={`Summary of ${meeting.title}`}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-expanded={!collapsed}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
        >
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700">
            <SparkIcon className="h-3 w-3" />
            AI summary
          </span>
          <span className="truncate text-sm font-semibold text-slate-900" title={meeting.title}>
            {meeting.title}
          </span>
          {date && !meeting.title.includes(date) && <span className="shrink-0 text-sm text-slate-400">{date}</span>}
          <svg viewBox="0 0 20 20" className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${collapsed ? "-rotate-90" : ""}`} fill="currentColor" aria-hidden>
            <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
          </svg>
        </button>
        {canEdit && summary && !working && !collapsed && (
          <button
            type="button"
            onClick={onSummarise}
            title="Write this summary again"
            className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
          >
            Rewrite
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Hide summary"
            title="Hide summary"
            className="shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        )}
      </div>
      {!collapsed && <div className="mt-2.5">{body}</div>}
    </section>
  );
}

function SparkIcon({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 20 20" className={className} fill="currentColor" aria-hidden>
      <path d="M10 2a.75.75 0 01.71.51l1.1 3.3a2 2 0 001.27 1.27l3.3 1.1a.75.75 0 010 1.42l-3.3 1.1a2 2 0 00-1.27 1.27l-1.1 3.3a.75.75 0 01-1.42 0l-1.1-3.3a2 2 0 00-1.27-1.27l-3.3-1.1a.75.75 0 010-1.42l3.3-1.1a2 2 0 001.27-1.27l1.1-3.3A.75.75 0 0110 2z" />
    </svg>
  );
}
