"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { workspaceTokenFor } from "@/lib/session";
import type { AgentReview, AgentReviewListItem, Project, Task } from "@/lib/types";

export default function PendingTaskUpdates({ project, refreshKey, boardTasks, onReview, onHistory }: {
  project: Project;
  refreshKey: string;
  boardTasks: Task[];
  onReview: (review: AgentReview) => void;
  onHistory: () => void;
}) {
  const [pending, setPending] = useState<AgentReviewListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const token = workspaceTokenFor(project);

  useEffect(() => {
    let active = true;
    let requestId = 0;
    const refresh = async () => {
      const id = ++requestId;
      try {
        const rows = await api.listAgentReviews(project.id, token, "pending");
        if (active && id === requestId) { setPending(rows); setError(null); }
      } catch {
        if (active && id === requestId) setError("Couldn’t check for task updates.");
      }
    };
    void refresh();
    const onFocus = () => { void refresh(); };
    window.addEventListener("focus", onFocus);
    // Keep task validity and resolved changes current while this board stays open.
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 60_000);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", onFocus); };
  }, [project.id, token, refreshKey, boardTasks, retry]);

  useEffect(() => {
    if (!expanded) return;
    const close = (event: PointerEvent) => { if (!container.current?.contains(event.target as Node)) setExpanded(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); setExpanded(false); trigger.current?.focus(); } };
    window.addEventListener("pointerdown", close); window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("pointerdown", close); window.removeEventListener("keydown", escape); };
  }, [expanded]);

  async function review(id: string) {
    if (loadingId) return;
    setLoadingId(id); setError(null);
    try { onReview(await api.getAgentReview(project.id, id, token)); setExpanded(false); }
    catch (err) { setError((err as Error).message); }
    finally { setLoadingId(null); }
  }

  const count = pending.reduce((sum, item) => sum + item.change_count, 0);
  return <div ref={container} className="relative" aria-label="Suggested changes and history">
    <button ref={trigger} aria-label={loadingId ? "Opening suggested changes" : count ? `Review ${count} suggested change${count === 1 ? "" : "s"}` : "Changes"}
      aria-expanded={expanded} aria-busy={!!loadingId}
      aria-controls={expanded ? "suggested-changes-list" : undefined} disabled={!!loadingId}
      className={`inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg border bg-white px-3 text-[13px] font-medium transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-wait sm:text-sm ${expanded ? "border-slate-300 text-slate-800" : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-800"}`}
      onClick={() => setExpanded(v => !v)}>
      Changes
      {/* While a review opens, a spinner takes the badge's place, so the button keeps its width. */}
      {loadingId
        ? <svg className="h-5 w-5 animate-spin text-brand" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
          </svg>
        : count > 0 && <span aria-hidden="true" className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-brand px-1.5 text-[11px] font-semibold tabular-nums leading-none text-white">{count}</span>}
      <svg className={`h-3 w-3 text-slate-400 transition ${expanded ? "rotate-180" : ""}`} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="m4 6 4 4 4-4" /></svg>
    </button>
    {expanded && <div id="suggested-changes-list" className="absolute right-0 top-full z-30 mt-2 w-[min(300px,calc(100vw-40px))] rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
      <p className="px-2 py-1.5 text-xs font-semibold text-ink">Suggested changes</p>
      {pending.length === 0 && !error && <p className="px-2 pb-3 pt-1 text-xs text-slate-400">Nothing awaiting approval.</p>}
      {pending.map(item => <button key={item.id} disabled={!!loadingId} onClick={() => void review(item.id)} className="flex w-full items-center gap-2 rounded-lg px-2 py-2.5 text-left hover:bg-slate-50 disabled:opacity-50">
        <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-700">{item.title}</span>
          <span className="mt-1 block text-[11px] text-slate-400">{item.change_count || !item.possible_duplicates
            ? `${item.change_count} change${item.change_count === 1 ? "" : "s"}`
            : `${item.possible_duplicates} possible duplicate${item.possible_duplicates === 1 ? "" : "s"}`}{item.stale ? " · Refresh available" : ""}</span></span>
        <span className="text-slate-400" aria-hidden="true">›</span>
      </button>)}
      {error && <p role="alert" className="px-2 py-2 text-xs text-rose-700">{error} <button className="underline" onClick={() => setRetry(n => n + 1)}>Try again</button></p>}
      <div className="mt-1 border-t border-slate-100 pt-1">
        <button className="flex min-h-10 w-full items-center gap-2 rounded-lg px-2 text-left text-xs font-medium text-slate-600 hover:bg-slate-50" onClick={() => { setExpanded(false); onHistory(); }}>
          <svg className="h-4 w-4 text-slate-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M3.5 7A7 7 0 1 1 3 11m.5-7v3.5H7M10 6v4l2.5 1.5" /></svg>
          Recent changes
        </button>
      </div>
    </div>}
  </div>;
}
