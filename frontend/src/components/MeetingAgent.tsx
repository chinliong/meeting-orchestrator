"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { workspaceTokenFor } from "@/lib/session";
import type { AgentMutation, AgentReview, AgentReviewListItem, AgentTaskFields, Project } from "@/lib/types";

const PRIMARY = "rounded-lg bg-ink px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50";
const SECONDARY = "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50";
const FIELD_LABELS: Record<keyof AgentTaskFields, string> = { description: "Task", owner: "Owner", deadline: "Deadline", status: "Status" };
const display = (value: string | null) => value === null ? "Not set" : ({ todo: "To do", in_progress: "In progress", done: "Done" }[value] ?? value);
const KIND: Record<AgentReview["mode"], string> = { meeting: "Meeting added", meeting_updates: "Suggested changes", chat: "Suggested changes" };
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const countLabel = (mode: AgentReview["mode"], n: number) =>
  mode === "meeting" ? plural(n, "new task") : plural(n, "change");
// Suggested changes start ticked; possible duplicates start unticked, since the assistant
// believes they are already on the board.
const defaultSelection = (review?: AgentReview | null) =>
  review?.proposals.filter(p => !p.possible_duplicate && !review.unavailable_proposal_ids?.includes(p.id)).map(p => p.id);
const when = (iso: string) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function StatusLabel({ status }: { status: string }) {
  const [label, dot] = status === "draft" ? ["Pending approval", "bg-status-progress"]
    : status === "undone" ? ["Undone", "bg-slate-400"]
    : status === "dismissed" ? ["Dismissed", "bg-slate-400"]
    : ["Applied", "bg-status-done"];
  return <span className="inline-flex shrink-0 items-center gap-2">
    <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
    <span className="font-display text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
  </span>;
}

export interface ReviewLaunch {
  id: number;
  review?: AgentReview;
}

export default function MeetingAgent({ project, onChanged, launch, onClose, onReviewChanged, reviewEvent, onNewMeeting }: {
  project: Project;
  onChanged: (review: AgentReview, action: AgentMutation) => void;
  launch: ReviewLaunch | null;
  reviewEvent: AgentReview | null;
  onNewMeeting: () => void;
  onClose: () => void;
  onReviewChanged: (review: AgentReview) => void;
}) {
  const [open, setOpen] = useState(false);
  const [review, setReview] = useState<AgentReview | null>(null);
  // True when the review was opened from the Recent changes list, so Back can return to it.
  const [fromList, setFromList] = useState(false);
  const [history, setHistory] = useState<AgentReviewListItem[] | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState<"apply" | "undo" | "load" | "refresh" | "dismiss" | null>(null);
  const [confirmRemoval, setConfirmRemoval] = useState(false);
  const cancelRemoval = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const token = workspaceTokenFor(project);

  useEffect(() => {
    if (!launch) return;
    setReview(launch.review ?? null);
    setFromList(false);
    setSelected(launch.review?.receipt?.proposal_ids ?? defaultSelection(launch.review) ?? []);
    setError(null); setConfirmRemoval(false);
    setOpen(true);
    void loadHistory();
    // A launch is an explicit action, not a re-render of its parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [launch]);

  useEffect(() => {
    if (reviewEvent && reviewEvent.id === review?.id) setReview(reviewEvent);
    // External Undo updates the open detail without reopening a dismissed dialog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewEvent]);

  useEffect(() => { if (confirmRemoval) cancelRemoval.current?.focus(); }, [confirmRemoval]);

  const close = () => { setConfirmRemoval(false); setOpen(false); onClose(); };

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    const previousFocus = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    dialog.current?.focus({ preventScroll: true });
    return () => { document.body.style.overflow = previous; if (previousFocus?.isConnected) previousFocus.focus(); };
  }, [open]);

  // Switching between the list and a saved review can remove the focused button. Keep
  // keyboard focus in the dialog, and handle Escape even during that transition.
  useEffect(() => { if (open) dialog.current?.focus({ preventScroll: true }); }, [open, review?.id]);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopImmediatePropagation();
        if (!busy) { if (confirmRemoval) setConfirmRemoval(false); else { setOpen(false); onClose(); } }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, busy, onClose, confirmRemoval]);

  async function loadHistory() {
    try {
      const result = await api.listAgentReviews(project.id, token, "history");
      if (mounted.current) setHistory(result);
    } catch (err) {
      if (mounted.current) setError((err as Error).message);
    }
  }

  async function perform(action: "apply" | "undo" | "load" | "refresh" | "dismiss", id?: string) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(action); setError(null);
    try {
      const result = action === "load" ? await api.getAgentReview(project.id, id!, token)
        : action === "refresh" ? await api.refreshAgentReview(project.id, review!.id, token)
        : action === "apply" ? await api.applyAgentReview(project.id, review!.id, selected, token)
        : action === "dismiss" ? await api.dismissAgentReview(project.id, review!.id, token)
        : await api.undoAgentReview(project.id, review!.id, token);
      if (!mounted.current) return;
      setConfirmRemoval(false);
      if (action === "load") setFromList(true);
      setReview(result); setSelected(result.receipt?.proposal_ids ?? defaultSelection(result) ?? []);
      // Dismissing changes nothing on the board; it only refreshes the pending list.
      if (action !== "load") onChanged(result, action === "dismiss" ? "refresh" : action);
      onReviewChanged(result);
      await loadHistory();
    } catch (err) {
      if (mounted.current) {
        setError((err as Error).message);
        // Recover a lost mutation response and keep the board's Undo in sync.
        if (review && action !== "load") {
          try {
            const current = await api.getAgentReview(project.id, review.id, token);
            if (mounted.current) {
              setReview(current); onReviewChanged(current);
              if (current.status !== review.status) {
                const ours = action === "apply" && current.status === "applied" && JSON.stringify(current.receipt?.proposal_ids) === JSON.stringify([...selected].sort((a, b) => a - b));
                onChanged(current, ours ? "apply" : action === "undo" && current.status === "undone" ? "undo" : "refresh");
                setError(null);
              }
            }
          } catch { /* Leave the original error visible. */ }
        }
        await loadHistory();
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(null);
    }
  }

  const backToList = () => { setReview(null); setFromList(false); setError(null); void loadHistory(); };

  const expired = !!review && new Date(review.expires_at || "9999-12-31").getTime() < Date.now();
  const editable = review?.status === "draft" && !expired && (!review.stale || !!review.unavailable_proposal_ids);
  const mode = review?.mode ?? "meeting";
  const isDraft = review?.status === "draft";
  // Once saved, show only what was actually applied.
  const shown = review ? (review.receipt ? review.proposals.filter(p => review.receipt!.proposal_ids.includes(p.id)) : review.proposals) : [];
  const sourceUnavailable = review?.stale_reason?.startsWith("The source meeting");
  const changes = shown.filter(p => !(isDraft && p.possible_duplicate));
  const duplicates = isDraft ? shown.filter(p => p.possible_duplicate) : [];
  const eligible = changes.filter(p => !review?.unavailable_proposal_ids?.includes(p.id));
  const appliedCount = review?.receipt?.proposal_ids.length ?? 0;
  const statusLine = !review ? "" : isDraft
    ? (mode === "meeting_updates" ? "The meeting and its new tasks are already saved. Review the suggested changes." : "Deselect anything you don’t want.")
    : review.status === "dismissed" ? "These suggested changes were dismissed. Nothing on the board changed."
    : review.status === "applied"
      ? (mode === "meeting" ? `Added this meeting and ${plural(appliedCount, "new task")}.` : `Applied ${plural(appliedCount, "change")}.`)
      : (mode === "meeting" ? "This meeting and the tasks it added were removed." : "These changes were reversed.");

  return <>
    {open && createPortal(
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-2 backdrop-blur-sm sm:p-6">
        <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="agent-title" tabIndex={-1}
          className="flex max-h-[94dvh] w-full max-w-2xl flex-col overflow-clip rounded-2xl bg-slate-50 shadow-2xl outline-none"
          onKeyDown={e => {
            if (e.key === "Tab") {
              const elements = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), summary, [tabindex="0"]');
              if (!elements?.length) { e.preventDefault(); return; }
              const first = elements[0], last = elements[elements.length - 1];
              if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { e.preventDefault(); last.focus(); }
              else if (!e.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { e.preventDefault(); first.focus(); }
            }
          }}>
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-200 bg-white px-5 py-4 sm:px-7">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wider text-brand-700">{review ? KIND[mode] : project.name}</p>
              <h2 id="agent-title" className="mt-1 font-display text-xl font-bold text-slate-900">
                {!review ? "Recent changes" : isDraft ? "Suggested changes" : review.input.title}
              </h2>
            </div>
            <button aria-label="Close" disabled={!!busy} onClick={close} className={SECONDARY}>Close</button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
            {error && <div role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>}

            {!review ? <>
              <p className="mb-4 text-sm text-slate-600">Changes the assistant made to this board. Open one to see the details or undo it.</p>
              {history === null ? <p className="text-sm text-slate-500">Loading…</p>
                : history.length === 0 ? <p className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">No saved changes yet. Suggested changes appear on your board.</p>
                : <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
                  {history.map(h => <li key={h.id}>
                    <button disabled={!!busy} onClick={() => void perform("load", h.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-slate-50 disabled:opacity-60">
                      <span className="min-w-0 flex-1">
                        <span className="block text-[11px] font-semibold uppercase tracking-wide text-brand-700">{KIND[h.mode]}</span>
                        <span className="block truncate font-medium text-slate-900">{h.title}</span>
                        <span className="block text-xs text-slate-500">{countLabel(h.mode, h.change_count)} · {when(h.created_at)}</span>
                      </span>
                      <StatusLabel status={h.status} />
                      <span className="text-slate-400" aria-hidden="true">›</span>
                    </button>
                  </li>)}
                </ul>}
            </> : <div className="space-y-5">
              {fromList && <button disabled={!!busy} onClick={backToList} className="text-sm font-medium text-brand-900 hover:underline">← All recent changes</button>}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <div className="flex flex-wrap items-center gap-2">
                  {isDraft && <h3 className="font-semibold text-slate-900">{review.input.title}</h3>}
                  <span className="text-xs text-slate-500">{when(review.created_at)}</span>
                  <StatusLabel status={review.status} />
                </div>
                <p role="status" className="mt-2 text-sm text-slate-600">{statusLine}</p>
                <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer font-medium">{mode === "chat" ? "View your request" : "View transcript"}</summary>
                  <p className="mt-2 whitespace-pre-wrap leading-relaxed">{review.input.transcript}</p>
                </details>
              </section>
              {isDraft && review.stale && <p role="alert" className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">{sourceUnavailable ? "This meeting changed or was removed. Add the correct transcript to check these suggested changes." : "Your tasks changed. Refresh these suggested changes, or apply those still available."}</p>}
              {isDraft && review.questions.length > 0 && <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
                <h3 className="font-semibold text-amber-950">Needs your input</h3>
                <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-relaxed text-amber-900">{review.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
              </section>}
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-semibold text-slate-900">{plural(changes.length, "change")}</h3>
                {editable && eligible.length > 1 && <button className="text-sm font-medium text-brand-900 underline underline-offset-4" disabled={!!busy}
                  onClick={() => { const all = eligible.every(p => selected.includes(p.id)); const ids = new Set(eligible.map(p => p.id));
                    setSelected(all ? selected.filter(id => !ids.has(id)) : [...selected.filter(id => !ids.has(id)), ...ids]); }}>
                  {eligible.every(p => selected.includes(p.id)) ? "Clear selection" : "Select all"}</button>}
              </div>
              {changes.length === 0 && duplicates.length === 0 && <p className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600">{review.questions.length ? "No changes are ready to apply." : "Your tasks are already up to date."}</p>}
              {changes.map(p => <article key={p.id} className={`rounded-xl border bg-white p-4 sm:p-5 ${editable && selected.includes(p.id) ? "border-brand-500 ring-1 ring-brand-500" : "border-slate-200"}`}>
                <label className="flex items-start gap-3">
                  {editable && <input type="checkbox" checked={selected.includes(p.id)} disabled={!!busy || review.unavailable_proposal_ids?.includes(p.id)} className="mt-1 h-4 w-4 shrink-0 accent-brand-700"
                    onChange={e => setSelected(e.target.checked ? [...selected, p.id] : selected.filter(id => id !== p.id))} />}
                  <span><span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-brand-700">{p.kind === "create" ? "New task" : "Suggested change"}</span>
                    <span className="font-semibold text-slate-900">{p.after.description}</span></span>
                </label>
                {isDraft && review.unavailable_proposal_ids?.includes(p.id) && <p className="mt-2 text-xs text-slate-500">This task changed. Refresh to check the suggested change.</p>}
                <dl className="mt-4 space-y-2 text-sm">
                  {(Object.keys(FIELD_LABELS) as (keyof AgentTaskFields)[]).filter(k => !p.before || p.before[k] !== p.after[k]).map(k => <div key={k} className="grid grid-cols-[75px_1fr] gap-3">
                    <dt className="text-slate-500">{FIELD_LABELS[k]}</dt><dd className="min-w-0 break-words text-slate-800">
                      {p.before && <><span className="text-slate-500 line-through">{display(p.before[k])}</span><span className="mx-2 text-slate-400" aria-label="changes to">→</span></>}
                      <span className="font-medium">{display(p.after[k])}</span>
                    </dd></div>)}
                </dl>
                {/* A parser-extracted task carries its source decision, which may be paraphrased or empty. */}
                {p.evidence && <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">{p.confidence != null ? "Why this task?" : "Why this change?"}</summary><blockquote className="mt-2 border-l-2 border-brand-100 bg-brand-50/60 px-3 py-2 text-sm leading-relaxed text-slate-700">{p.confidence != null ? p.evidence : `“${p.evidence}”`}</blockquote></details>}
              </article>)}
              {duplicates.length > 0 && <details className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
                <summary className="cursor-pointer text-sm font-semibold text-slate-900">
                  Possible duplicates ({duplicates.length})
                  <span className="ml-1 font-normal text-slate-500">· Select any that are new tasks to add them</span>
                </summary>
                <ul className="mt-3 space-y-3">{duplicates.map(p => <li key={p.id}>
                  <label className="flex items-start gap-3 text-sm">
                    {editable && <input type="checkbox" checked={selected.includes(p.id)} disabled={!!busy} className="mt-0.5 h-4 w-4 shrink-0 accent-brand-700"
                      onChange={e => setSelected(e.target.checked ? [...selected, p.id] : selected.filter(id => id !== p.id))} />}
                    <span><span className="font-medium text-slate-900">Add “{p.after.description}”</span>
                      <span className="block text-xs text-slate-500">Possible duplicate of “{p.duplicate_of?.description}”</span></span>
                  </label>
                </li>)}</ul>
              </details>}
              {isDraft && <p className="text-xs text-slate-500">{expired ? "These suggested changes expired after an hour. Refresh to check them again." : "Items you don’t select are dismissed. Your tasks are checked again before any changes are applied."}</p>}
            </div>}
          </div>
          {review && <footer className="shrink-0 border-t border-slate-200 bg-white px-5 py-4 sm:px-7">
            {confirmRemoval ? <div role="group" aria-labelledby="remove-meeting-label">
              <p id="remove-meeting-label" className="text-sm font-semibold text-ink">Remove this meeting and {plural(appliedCount, "task")}?</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">This removes “{review.input.title}” and the tasks it added from your board. Viewing recent changes does not require removing anything.</p>
              <div className="mt-3 flex flex-wrap justify-end gap-2">
                <button ref={cancelRemoval} className={SECONDARY} disabled={!!busy} onClick={() => setConfirmRemoval(false)}>Keep meeting</button>
                <button className="rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50" disabled={!!busy} onClick={() => void perform("undo")}>{busy === "undo" ? "Removing…" : "Remove meeting & tasks"}</button>
              </div>
            </div> : <div className="flex flex-wrap items-center justify-between gap-3">
              <button className={SECONDARY} disabled={!!busy} onClick={close}>{isDraft ? "Not now" : "Done"}</button>
              {isDraft && (sourceUnavailable || (expired && mode === "meeting")) && <button className={SECONDARY} onClick={() => { close(); onNewMeeting(); }}>New meeting</button>}
              {isDraft && !sourceUnavailable && mode !== "meeting" && (expired || review.stale) && <button className={SECONDARY} disabled={!!busy} onClick={() => void perform("refresh")}>{busy === "refresh" ? "Refreshing…" : "Refresh"}</button>}
              {isDraft && (selected.length > 0
                ? <button className={PRIMARY} disabled={!!busy || !editable} onClick={() => void perform("apply")}>{busy === "apply" ? "Applying…" : `Apply ${selected.length}`}</button>
                : <button className={PRIMARY} disabled={!!busy} onClick={() => void perform("dismiss")}>{busy === "dismiss" ? "Dismissing…" : "Dismiss all"}</button>)}
              {review.status === "applied" && (mode === "meeting"
                ? <button className="rounded-lg px-3 py-2 text-xs text-slate-400 hover:bg-rose-50 hover:text-rose-700 focus-visible:ring-2 focus-visible:ring-rose-300" disabled={!!busy} onClick={() => setConfirmRemoval(true)}>Remove meeting…</button>
                : <button className={SECONDARY} disabled={!!busy} onClick={() => void perform("undo")}>{busy === "undo" ? "Undoing…" : "Undo these changes"}</button>)}
            </div>}
          </footer>}
        </div>
      </div>, document.body)}
  </>;
}
