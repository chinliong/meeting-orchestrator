"use client";

import { useEffect, useRef, useState } from "react";
import { formatMeetingDate } from "@/lib/format";
import { api } from "@/lib/api";
import type { AgentMutation, AgentProposal, AgentReview, AgentTaskFields } from "@/lib/types";

const LABELS: Record<keyof AgentTaskFields, string> = { description: "Task", owner: "Owner", deadline: "Deadline", status: "Status" };
const value = (text: string | null, key?: keyof AgentTaskFields) => key === "deadline" && text ? formatMeetingDate(text) : text === null ? "Unassigned" : ({ todo: "To do", in_progress: "In progress", done: "Done" }[text] || text);
const BUTTON = "rounded-lg px-3 py-2 text-xs font-semibold transition focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50";

export function ChangeDetails({ change }: { change: AgentProposal }) {
  return <div className="space-y-2">
    <p className="text-[13px] font-semibold leading-relaxed text-ink">{change.before?.description || change.after.description}</p>
    <dl className="space-y-1.5 text-xs leading-relaxed">
      {(Object.keys(LABELS) as (keyof AgentTaskFields)[]).filter(key => !change.before || change.before[key] !== change.after[key]).map(key =>
        <div key={key} className="grid grid-cols-[60px_1fr] gap-2">
          <dt className="text-slate-400">{LABELS[key]}</dt>
          <dd className="min-w-0 break-words text-slate-700">{change.before && <><span className="text-slate-400 line-through">{change.before[key] === null ? "Not set" : value(change.before[key], key)}</span><span className="mx-1.5 text-slate-400" aria-label="changes to">→</span></>}{change.after[key] === null ? "Not set" : value(change.after[key], key)}</dd>
        </div>)}
    </dl>
    <details className="text-[11px] leading-relaxed text-slate-500"><summary className="cursor-pointer hover:text-brand">Why this change?</summary><blockquote className="mt-2 border-l-2 border-brand-100 pl-2">“{change.evidence}”</blockquote></details>
  </div>;
}

export default function SuggestedChanges({ projectId, token, review, onReview, onChanged }: {
  projectId: number;
  token: string;
  review: AgentReview;
  onReview: (review: AgentReview) => void;
  onChanged: (review: AgentReview, action: AgentMutation) => void;
}) {
  const [busy, setBusy] = useState<AgentMutation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const expired = !!review.expires_at && new Date(review.expires_at).getTime() < Date.now();
  const ids = review.proposals.filter(p => !review.unavailable_proposal_ids?.includes(p.id)).map(p => p.id);
  const needsRefresh = expired || review.stale;
  async function perform(action: AgentMutation) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(action); setError(null);
    try {
      const result = action === "apply" ? await api.applyAgentReview(projectId, review.id, ids, token)
        : action === "undo" ? await api.undoAgentReview(projectId, review.id, token)
        : await api.refreshAgentReview(projectId, review.id, token);
      if (!mounted.current) return;
      onReview(result); onChanged(result, action);
    } catch (err) {
      if (mounted.current) {
        setError((err as Error).message);
        // A lost response can still have committed. Recover the authoritative state.
        try {
          const current = await api.getAgentReview(projectId, review.id, token);
          if (mounted.current) {
            onReview(current);
            if (current.status !== review.status) {
              const ours = action === "apply" && current.status === "applied" && JSON.stringify(current.receipt?.proposal_ids) === JSON.stringify([...ids].sort((a, b) => a - b));
              onChanged(current, ours ? "apply" : action === "undo" && current.status === "undone" ? "undo" : "refresh");
            }
          }
        } catch { /* Keep the original error and allow an explicit retry. */ }
      }
    } finally { inFlight.current = false; if (mounted.current) setBusy(null); }
  }
  const shown = review.receipt ? review.proposals.filter(p => review.receipt!.proposal_ids.includes(p.id)) : review.proposals;
  return <section aria-label="Suggested changes" className="mt-3 rounded-xl border border-slate-200 bg-white">
    <div className="border-b border-slate-100 px-3 py-2.5 text-xs font-semibold text-ink">{review.status === "applied" ? "Changes applied" : review.status === "undone" ? "Changes undone" : "Suggested changes"}</div>
    <div className="divide-y divide-slate-100">{shown.map(change => <div key={change.id} className="p-3"><ChangeDetails change={change} /></div>)}</div>
    {shown.length === 0 && <p className="p-3 text-xs text-slate-500">{review.questions.length ? "No changes are ready to apply." : "Your tasks are already up to date."}</p>}
    {review.questions.length > 0 && <ul className="space-y-1 px-3 pb-2 text-xs leading-relaxed text-slate-500">{review.questions.map((question, index) => <li key={index}>{question}</li>)}</ul>}
    {needsRefresh && review.status === "draft" && <p className="px-3 pb-2 text-xs leading-relaxed text-slate-500">{expired ? "These suggested changes expired after an hour. Refresh to check them again." : review.stale_reason || "Your tasks changed. Refresh to check these suggested changes."}</p>}
    {error && <p role="alert" className="px-3 pb-2 text-xs leading-relaxed text-rose-700">{error}</p>}
    <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-3 py-2">
      {review.status === "draft" && <>
        {ids.length > 0 && !expired && <button disabled={!!busy} onClick={() => void perform("apply")} className={`${BUTTON} bg-ink text-white hover:bg-ink-700`}>{busy === "apply" ? "Applying…" : "Apply"}</button>}
        {needsRefresh && <button disabled={!!busy} onClick={() => void perform("refresh")} className={`${BUTTON} text-brand hover:bg-brand-50`}>{busy === "refresh" ? "Refreshing…" : "Refresh"}</button>}
      </>}
      {review.status === "applied" && <button disabled={!!busy} onClick={() => void perform("undo")} className={`${BUTTON} text-slate-600 hover:bg-slate-100`}>{busy === "undo" ? "Undoing…" : "Undo"}</button>}
      {busy && <span role="status" className="sr-only">{busy === "refresh" ? "Refreshing suggested changes" : "Saving changes"}</span>}
    </div>
  </section>;
}
