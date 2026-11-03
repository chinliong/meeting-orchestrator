"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import SuggestedChanges from "@/components/SuggestedChanges";
import { api } from "@/lib/api";
import { workspaceTokenFor } from "@/lib/session";
import type { AgentMutation, AgentReview, AssistantAnswer, AssistantMessage, AssistantSource, Project } from "@/lib/types";

interface Turn extends AssistantMessage {
  id: number;
  response?: AssistantAnswer;
}

const STARTERS = [
  { title: "What's overdue?", detail: "Check deadlines", prompt: "Which tasks are overdue, and who owns them?" },
  { title: "Who's working on what?", detail: "See current work", prompt: "What is each person currently working on?" },
  { title: "What did we decide?", detail: "Look back at meetings", prompt: "What were the key decisions in our most recent meeting?" },
];

function AnswerText({ text }: { text: string }) {
  const inline = (line: string): ReactNode => line.split(/(\*\*[^*\n]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={index} className="font-semibold">{part.slice(2, -2)}</strong> : part);
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: ReactNode[] = [];
      const key = i;
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        items.push(<li key={i}>{inline(lines[i].replace(/^\s*[-*•]\s+/, ""))}</li>); i++;
      }
      i--; blocks.push(<ul key={key} className="list-disc space-y-1.5 pl-4">{items}</ul>);
    } else if (/^#{1,4}\s/.test(line)) {
      blocks.push(<p key={i} className="font-semibold text-ink">{inline(line.replace(/^#{1,4}\s+/, ""))}</p>);
    } else if (!/^[-*_]{3,}\s*$/.test(line)) {
      blocks.push(<p key={i}>{inline(line)}</p>);
    }
  }
  // Only React text nodes; links and model output never become executable HTML.
  return <div className="space-y-3 break-words text-[13px] leading-[1.75] text-slate-700">{blocks}</div>;
}

function CopyAnswer({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 2500);
    return () => clearTimeout(timer);
  }, [state]);
  return <button className="rounded-md px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus-visible:ring-2 focus-visible:ring-brand" onClick={async () => {
    try { await navigator.clipboard.writeText(text); setState("copied"); } catch { setState("error"); }
  }} aria-label="Copy answer">{state === "copied" ? "Copied" : state === "error" ? "Couldn’t copy" : "Copy"}</button>;
}

function AssistantIcon({ className = "h-6 w-6" }: { className?: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className} aria-hidden="true">
    <path strokeLinecap="round" strokeLinejoin="round" d="M19 11.5v4a3 3 0 0 1-3 3H9l-5 3v-6a7.5 7.5 0 0 1-1-3.75A7.75 7.75 0 0 1 10.75 4H13" />
    <path strokeLinecap="round" strokeLinejoin="round" d="m18 2 1.1 3.4L22.5 6.5l-3.4 1.1L18 11l-1.1-3.4-3.4-1.1 3.4-1.1L18 2Z" />
    <path strokeLinecap="round" d="M8 11h4m-4 3h7" />
  </svg>;
}

function SourceCard({ source, index, onOpen }: { source: AssistantSource; index: number; onOpen: () => void }) {
  const status = source.status ? { todo: "To do", in_progress: "In progress", done: "Done" }[source.status] : null;
  return <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs">
    <button onClick={onOpen} className="flex w-full items-start gap-2 text-left hover:text-brand">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-brand-50 text-[10px] font-semibold text-brand">{index + 1}</span>
      <span className="min-w-0"><span className="block font-medium leading-relaxed">{source.title}</span>
        <span className="mt-1 block text-[11px] text-slate-400">{source.kind === "task" ? [source.owner || "Unassigned", status, source.deadline ? `Due ${source.deadline}` : null].filter(Boolean).join(" · ") : "Meeting"}</span>
      </span><span className="ml-auto text-slate-400" aria-hidden="true">→</span>
    </button>
    <details className="mt-2 text-[11px] leading-relaxed text-slate-500"><summary className="cursor-pointer hover:text-brand">Evidence</summary><blockquote className="mt-2 border-l-2 border-brand-100 pl-2">“{source.quote}”</blockquote></details>
  </div>;
}

export default function ProjectAssistant({ project, onChanged, onOpenTask, onOpenMeeting, onNewMeeting, meetingCount, onSuggestionsChanged, onOpenReview, onOpenChange, open, inlineReview, reviewEvent }: {
  project: Project;
  onNewMeeting: () => void;
  meetingCount: number;
  onSuggestionsChanged: () => void;
  onChanged: (review: AgentReview, action: AgentMutation) => void;
  onOpenReview: (review: AgentReview) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  inlineReview: AgentReview | null;
  reviewEvent: AgentReview | null;
  onOpenTask: (id: number) => void;
  onOpenMeeting: (id: number) => void;
}) {
  const setOpen = onOpenChange;
  const [messages, setMessages] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [failedMessage, setFailedMessage] = useState<string | null>(null);
  const [unread, setUnread] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const wasOpened = useRef(false);
  const scroll = useRef<HTMLDivElement>(null);
  const followBottom = useRef(true);
  const [newReply, setNewReply] = useState(false);
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const openRef = useRef(open);
  openRef.current = open;
  const sequence = useRef(0);
  const canEdit = project.access_level === "edit";
  const token = workspaceTokenFor(project);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (open) { wasOpened.current = true; setUnread(false); input.current?.focus({ preventScroll: true }); }
    else if (wasOpened.current) launcher.current?.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => {
    if (open && scroll.current && followBottom.current) { scroll.current.scrollTop = scroll.current.scrollHeight; setNewReply(false); }
  }, [messages, busy, open]);
  useEffect(() => {
    if (!busy) return;
    setSeconds(0);
    const timer = setInterval(() => setSeconds(s => s + 1), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (!reviewEvent) return;
    setMessages(current => current.map(message => message.response?.review?.id === reviewEvent.id
      ? { ...message, response: { ...message.response, review: reviewEvent } } : message));
  }, [reviewEvent]);

  useEffect(() => {
    if (!inlineReview) return;
    setMessages(current => current.some(message => message.response?.review?.id === inlineReview.id)
      ? current.map(message => message.response?.review?.id === inlineReview.id ? { ...message, response: { ...message.response, review: inlineReview } } : message)
      : [...current, { id: ++sequence.current, role: "assistant", content: "Review the changes below.", response: {
          answer: "Review the changes below.", sources: [], questions: inlineReview.questions, next_action: "none", review: inlineReview,
          model: inlineReview.model, trace: inlineReview.trace, elapsed_seconds: inlineReview.elapsed_seconds,
        } }]);
    setOpen(true);
  }, [inlineReview]);

  const closeChat = () => { setOpen(false); launcher.current?.focus({ preventScroll: true }); };

  async function send(message: string, retry = false) {
    const text = message.trim();
    if (!text || inFlight.current || text.length > 8000) return;
    const previous = retry ? messages.slice(0, -1) : messages;
    const history = previous.slice(-12).map(({ role, content, response }) => ({
      role,
      content: (response?.review ? `${content}\nSuggestion status: ${response.review.status}.` : content).slice(0, 8000),
    }));
    if (!retry) setMessages([...messages, { id: ++sequence.current, role: "user", content: text }]);
    if (!retry) setDraft("");
    followBottom.current = true; setNewReply(false);
    setError(null); setFailedMessage(null); setBusy(true); inFlight.current = true;
    try {
      const response = await api.chatWithAssistant(project.id, text, history, new Date().toLocaleDateString("en-CA"), token);
      if (!mounted.current) return;
      setMessages(current => [...current, { id: ++sequence.current, role: "assistant", content: response.answer, response }]);
      if (!followBottom.current) setNewReply(true);
      if (response.review) onSuggestionsChanged();
      if (!openRef.current) setUnread(true);
    } catch (err) {
      if (mounted.current) { setError((err as Error).message); setFailedMessage(text); }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const updateReview = (review: AgentReview) => setMessages(current => current.map(message =>
    message.response?.review?.id === review.id ? { ...message, response: { ...message.response, review } } : message));

  return <>
    {!open && <div className="group fixed bottom-5 right-4 z-40 sm:bottom-6 sm:right-6">
      {!open && <span role="tooltip" id="assistant-launcher-tip" className="pointer-events-none invisible absolute bottom-3 right-[68px] hidden whitespace-nowrap rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-card opacity-0 transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 motion-reduce:transition-none sm:block">Project assistant</span>}
      <button ref={launcher} aria-label={open ? "Close project assistant" : "Open project assistant"} aria-describedby={!open ? "assistant-launcher-tip" : undefined} aria-expanded={open} aria-controls="project-assistant"
        onClick={() => setOpen(true)}
        className="relative flex h-14 w-14 items-center justify-center rounded-full bg-brand text-white shadow-brand transition hover:bg-brand-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-100">
        {open ? <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" /></svg> : <AssistantIcon />}
        {unread && !open && <span aria-label="New reply" className="absolute right-0 top-0 h-3 w-3 rounded-full border-2 border-white bg-status-done" />}
      </button>
    </div>}

    {open && <section id="project-assistant" role="dialog" aria-labelledby="assistant-title"
      className="fixed bottom-[88px] right-3 z-40 flex h-[min(620px,calc(100dvh-108px))] w-[calc(100vw-24px)] max-w-[400px] flex-col overflow-clip rounded-2xl border border-slate-200 bg-white shadow-ink sm:bottom-[96px] sm:right-6 lg:bottom-6 lg:right-4 lg:top-20 lg:h-auto lg:w-[360px] lg:shadow-card"
      onKeyDown={e => {
        if (e.key === "Escape") { e.stopPropagation(); closeChat(); }
      }}>
      <header className="flex shrink-0 items-center gap-2 bg-ink px-4 py-3 text-white">
        <AssistantIcon className="h-5 w-5 text-brand-100" />
        <h2 id="assistant-title" className="min-w-0 flex-1 truncate font-display text-[15px] font-semibold">Project assistant</h2>
        {!canEdit && <span className="text-[10px] text-slate-400">View only</span>}
        <button aria-label="New chat" title="New chat" disabled={busy || messages.length === 0} onClick={() => { followBottom.current = true; setNewReply(false); setMessages([]); setError(null); setFailedMessage(null); input.current?.focus(); }} className="shrink-0 whitespace-nowrap rounded-lg px-2 py-2 text-xs font-medium text-slate-300 hover:bg-white/10 hover:text-white disabled:opacity-30">
          New chat
        </button>
        <button aria-label="Minimise assistant" onClick={closeChat} className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white"><svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" /></svg></button>
      </header>

      <div ref={scroll} onScroll={e => { const el = e.currentTarget; followBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60; if (followBottom.current) setNewReply(false); }} className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-slate-50/70 p-4">
        {messages.length === 0 && <div className="pb-2 pt-5">
          <h3 className="font-display text-xl font-bold tracking-tight text-slate-900">What would you like to know?</h3>
          <p className="mt-2 text-sm leading-relaxed text-slate-500">Ask about your tasks and meeting decisions.{canEdit ? " Changes are always yours to approve." : " I can help you explore this read-only board."}</p>
          {canEdit && <button onClick={() => { closeChat(); onNewMeeting(); }} className="mt-2 text-xs font-medium text-brand hover:underline">Add a meeting →</button>}
          <div className="mt-4 space-y-2">
            {[...STARTERS, ...(meetingCount >= 2 ? [{ title: "What changed between meetings?", detail: "Compare the latest two", prompt: "Compare the two most recent saved meetings. What changed in decisions and commitments?" }] : [])].map(starter => <button key={starter.title} onClick={() => void send(starter.prompt)} className="group flex w-full items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-left shadow-card transition hover:border-brand-100 hover:bg-brand-50/40">
              <span><span className="block text-[13px] font-semibold text-slate-700">{starter.title}</span><span className="mt-0.5 block text-[11px] text-slate-400">{starter.detail}</span></span>
              <span className="text-slate-400 group-hover:text-brand" aria-hidden="true">→</span>
            </button>)}
          </div>
        </div>}

        <div role="log" aria-label="Project conversation" aria-live="polite" aria-relevant="additions" className="space-y-5">
          {messages.map(message => message.role === "user" ? <div key={message.id} className="ml-7 rounded-2xl rounded-br-md bg-brand px-4 py-3 text-[13px] leading-relaxed text-white">
            <span className="sr-only">You: </span><p className="whitespace-pre-wrap break-words">{message.content}</p>
          </div> : <article key={message.id} className="min-w-0">
            <div className="mb-2 flex items-center justify-between gap-2"><span className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-400"><AssistantIcon className="h-3.5 w-3.5 text-brand" /> Project assistant</span><CopyAnswer text={message.content} /></div>
            <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white p-4 shadow-card">
              <AnswerText text={message.content} />
              {!!message.response?.questions.length && !message.response.review && <ul className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-[13px] leading-relaxed text-slate-600">{message.response.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>}
              {message.response?.review && (message.response.review.proposals.length <= 2 && message.response.review.mode === "chat"
                ? <SuggestedChanges projectId={project.id} token={token} review={message.response.review} onReview={updateReview} onChanged={onChanged} />
                : <button onClick={() => onOpenReview(message.response!.review!)} className="mt-3 rounded-lg bg-ink px-3 py-2 text-xs font-semibold text-white hover:bg-ink-700">Review changes</button>)}
              {canEdit && message.response?.next_action === "review_meeting" && <button className="mt-4 w-full rounded-lg bg-ink px-3 py-2.5 text-xs font-semibold text-white hover:bg-ink-700"
                onClick={() => { closeChat(); onNewMeeting(); }}>Go to New meeting</button>}
              {process.env.NEXT_PUBLIC_AGENT_DEBUG === "true" && message.response && <details className="mt-3 text-[10px] text-slate-400"><summary className="cursor-pointer">Checked project context · {message.response.elapsed_seconds}s</summary>
                <ul className="mt-2 space-y-1">{message.response.trace.map((t, i) => <li key={i}>{t.label}</li>)}</ul>
                <p className="mt-2">{message.response.model}</p>
              </details>}
            </div>
            {!!message.response?.sources.length && <div className="mt-2 space-y-1.5">
              {message.response.sources.map((source, index) => <SourceCard key={`${source.kind}:${source.id}`} source={source} index={index} onOpen={() => {
                setOpen(false);
                if (source.kind === "task") onOpenTask(source.id); else onOpenMeeting(source.id);
              }} />)}
            </div>}
          </article>)}
        </div>

        {busy && <div role="status" className="mt-5 flex items-center gap-2 text-xs text-slate-500"><span className="h-3 w-3 animate-spin rounded-full border-2 border-brand-100 border-t-brand motion-reduce:animate-none" />
          {seconds < 15 ? "Checking your project…" : `Reading project context… ${seconds}s`}</div>}
        {error && <div role="alert" className="mt-4 rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs leading-relaxed text-rose-700">{error}
          {failedMessage && <button className="mt-2 block font-semibold underline" onClick={() => void send(failedMessage, true)}>Try again</button>}
        </div>}
      </div>

      {newReply && <button onClick={() => { followBottom.current = true; setNewReply(false); if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }} className="mx-auto -mt-9 mb-2 z-10 rounded-full border border-brand-100 bg-white px-3 py-1.5 text-xs font-semibold text-brand shadow-card">New reply ↓</button>}
      <footer className="shrink-0 border-t border-slate-200 bg-white p-3">
        <form onSubmit={e => { e.preventDefault(); void send(draft); }} className="flex items-end gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/10">
          <label className="sr-only" htmlFor="assistant-message">Message the project assistant</label>
          <textarea ref={input} id="assistant-message" rows={2} maxLength={8000} value={draft} onChange={e => setDraft(e.target.value)}
            placeholder="Ask about this project…" className="max-h-32 min-h-[42px] flex-1 resize-none bg-transparent text-[13px] leading-relaxed text-slate-700 outline-none placeholder:text-slate-400"
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(draft); } }} />
          <button type="submit" aria-label="Send message" disabled={busy || !draft.trim()} className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand text-white transition hover:bg-brand-700 disabled:bg-slate-200 disabled:text-slate-400">
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M10 16V4m-5 5 5-5 5 5" /></svg>
          </button>
        </form>
      </footer>
    </section>}

  </>;
}
