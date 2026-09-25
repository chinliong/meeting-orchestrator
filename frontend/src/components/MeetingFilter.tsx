"use client";

import { useEffect, useRef, useState } from "react";

import { formatAddedAt } from "@/lib/format";
import type { MeetingListItem } from "@/lib/types";

interface Props {
  /** The board's meetings, newest first. */
  meetings: MeetingListItem[];
  /** The meeting the board is filtered to; null shows every meeting's tasks. */
  selectedMeetingId: number | null;
  onSelect: (meetingId: number | null) => void;
  /** The meeting just added in this session, marked "New". */
  latestMeetingId: number | null;
  canEdit: boolean;
  onDelete: (meeting: MeetingListItem) => void;
}

/**
 * The Meeting filter in the board's Filter row: shows the board's meetings, newest first, with
 * when each was added and how many tasks it produced. Picking one shows only that meeting's
 * tasks, so an accidental second paste is easy to see, and to remove with its delete button.
 */
export default function MeetingFilter({ meetings, selectedMeetingId, onSelect, latestMeetingId, canEdit, onDelete }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Two meetings added within the same minute (typically an accidental second paste) would read
  // identically, so those show the seconds too.
  const perMinute = new Map<string, number>();
  for (const m of meetings) {
    if (m.created_at) {
      const key = formatAddedAt(m.created_at);
      perMinute.set(key, (perMinute.get(key) ?? 0) + 1);
    }
  }
  const addedLabel = (iso: string) => formatAddedAt(iso, (perMinute.get(formatAddedAt(iso)) ?? 0) > 1);

  const selected = meetings.find((m) => m.id === selectedMeetingId) ?? null;
  // Name the chosen meeting; if another meeting has the same name, add when it was added.
  const selectedLabel =
    selected &&
    (meetings.some((m) => m.id !== selected.id && m.title === selected.title) && selected.created_at
      ? `${selected.title} · ${formatAddedAt(selected.created_at, true).split(", ").pop()}`
      : selected.title);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        title={selected ? `Showing tasks from ${selectedLabel}` : "Filter by meeting"}
        className={`inline-flex max-w-[19rem] items-center gap-1.5 rounded-full py-1 pl-3 pr-2 text-sm font-medium transition ${
          selected ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-900/5"
        }`}
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 opacity-70" fill="currentColor" aria-hidden>
          <path d="M4 4a2 2 0 012-2h5.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm3 5a.75.75 0 000 1.5h6a.75.75 0 000-1.5H7zm0 3a.75.75 0 000 1.5h4a.75.75 0 000-1.5H7z" />
        </svg>
        <span className="truncate">{selected ? selectedLabel : "All meetings"}</span>
        {!selected && <span className="text-slate-400">{meetings.length}</span>}
        <svg viewBox="0 0 20 20" className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} fill="currentColor" aria-hidden>
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        // On a phone the list opens as a sheet along the bottom of the screen, so it always fits
        // wherever the button has wrapped to; from sm up it is an ordinary dropdown.
        <div className="fixed inset-x-4 bottom-4 z-40 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:mt-2 sm:w-80 sm:rounded-xl sm:shadow-lg">
          <button
            type="button"
            onClick={() => {
              onSelect(null);
              setOpen(false);
            }}
            className={`flex w-full items-center justify-between border-b border-slate-100 px-4 py-2.5 text-left text-sm transition hover:bg-slate-50 ${
              selected ? "text-slate-700" : "font-medium text-slate-900"
            }`}
          >
            All meetings
            {!selected && (
              <svg viewBox="0 0 20 20" className="h-4 w-4 text-slate-900" fill="currentColor" aria-hidden>
                <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0l-3.5-3.5a1 1 0 011.4-1.4l2.8 2.79 6.8-6.79a1 1 0 011.4 0z" clipRule="evenodd" />
              </svg>
            )}
          </button>
          <ul className="max-h-[55vh] overflow-y-auto p-1 sm:max-h-80">
            {meetings.map((m) => {
              const busy = m.status === "processing" || m.status === "pending";
              const isNew = m.id === latestMeetingId;
              const active = m.id === selectedMeetingId;
              return (
                <li key={m.id} className={`flex items-start gap-1 rounded-lg ${active ? "bg-slate-100" : "hover:bg-slate-50"}`}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(m.id);
                      setOpen(false);
                    }}
                    className="min-w-0 flex-1 px-3 py-2 text-left"
                  >
                    <span className="flex items-center gap-1.5">
                      <span className={`truncate text-[13px] ${active ? "font-semibold text-slate-900" : "font-medium text-slate-800"}`} title={m.title}>
                        {m.title}
                      </span>
                      {isNew && (
                        <span className="shrink-0 rounded bg-brand-600 px-1 text-[10px] font-semibold uppercase tracking-wide text-white">
                          New
                        </span>
                      )}
                    </span>
                    <span className="block text-[11.5px] text-slate-500">
                      {m.created_at && <>Added {addedLabel(m.created_at)} · </>}
                      {busy ? (
                        <span className="text-amber-600">Processing…</span>
                      ) : m.status === "failed" ? (
                        <span className="text-rose-600">Failed</span>
                      ) : (
                        `${m.task_count} task${m.task_count === 1 ? "" : "s"}`
                      )}
                    </span>
                  </button>
                  {canEdit && (
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(false);
                        onDelete(m);
                      }}
                      disabled={busy}
                      aria-label={`Delete meeting ${m.title}`}
                      title={busy ? "Can be deleted once it has finished processing" : "Delete this meeting and its tasks"}
                      className="mr-1.5 mt-2 shrink-0 rounded p-1 text-slate-300 transition hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-300"
                    >
                      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
                        <path d="M8 2a1 1 0 00-1 1v1H4.5a.5.5 0 000 1H5v10a2 2 0 002 2h6a2 2 0 002-2V5h.5a.5.5 0 000-1H13V3a1 1 0 00-1-1H8zm1 2V3h2v1H9zM8 7a.75.75 0 01.75.75v6a.75.75 0 01-1.5 0v-6A.75.75 0 018 7zm4.75.75a.75.75 0 00-1.5 0v6a.75.75 0 001.5 0v-6z" />
                      </svg>
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
