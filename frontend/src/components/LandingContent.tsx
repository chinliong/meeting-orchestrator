import Link from "next/link";

// The marketing landing UI. Rendered both at /landing (direct) and at / for
// first-time visitors via the entry gate in app/page.tsx.

// ---- small presentational helpers -------------------------------------------------

function Icon({ path, className = "h-5 w-5" }: { path: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d={path} />
    </svg>
  );
}

// 24x24 icon paths
const ICONS = {
  bolt: "M13 2L3 14h7l-1 8 10-12h-7l1-8z",
  doc: "M6 2a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6H6zm7 1.5L18.5 9H13V3.5zM8 13h8v2H8v-2zm0 4h8v2H8v-2z",
  mic: "M12 14a3 3 0 003-3V5a3 3 0 10-6 0v6a3 3 0 003 3zm5-3a5 5 0 01-10 0H5a7 7 0 006 6.92V21h2v-3.08A7 7 0 0019 11h-2z",
  board:
    "M4 4h16a1 1 0 011 1v14a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1zm1 2v12h4V6H5zm6 0v8h4V6h-4zm6 0v5h2V6h-2z",
  calendar:
    "M7 2a1 1 0 011 1v1h8V3a1 1 0 112 0v1h1a2 2 0 012 2v13a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2h1V3a1 1 0 011-1zM5 9v10h14V9H5z",
  share:
    "M18 8a3 3 0 10-2.83-4H15a3 3 0 00.18 1.05L8.9 8.6a3 3 0 100 6.8l6.28 3.55A3 3 0 1016.2 17l-6.28-3.55a3 3 0 000-2.9L16.2 7A3 3 0 0018 8z",
  users:
    "M16 11a4 4 0 10-4-4 4 4 0 004 4zm-8 0a4 4 0 10-4-4 4 4 0 004 4zm0 2c-3 0-6 1.5-6 4.5V20h8v-2.5A5.6 5.6 0 019 13.2 7.6 7.6 0 008 13zm8 0a7 7 0 00-2 .28A5.5 5.5 0 0118 17.5V20h6v-2.5c0-3-3-4.5-6-4.5z",
  shield:
    "M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5l8-3zm0 4.2L7 8v3.5c0 3.4 2.1 6.4 5 7.7 2.9-1.3 5-4.3 5-7.7V8l-5-1.8z",
  check: "M9.5 17.2l-4.7-4.7 1.4-1.4 3.3 3.3 7.3-7.3 1.4 1.4z",
  checklist:
    "M3 5h2v2H3V5zm4 .5h14v1.5H7V5.5zM3 11h2v2H3v-2zm4 .5h14V13H7v-1.5zM3 17h2v2H3v-2zm4 .5h14V19H7v-1.5z",
  bell: "M12 2a6 6 0 00-6 6v3.6L4 15v1h16v-1l-2-3.4V8a6 6 0 00-6-6zm0 20a3 3 0 002.83-2H9.17A3 3 0 0012 22z",
  paperclip:
    "M16.5 6.5l-7.8 7.8a2 2 0 102.83 2.83l7.07-7.07a4 4 0 10-5.66-5.66L5.1 11.9a6 6 0 108.49 8.49l6.36-6.36-1.41-1.41-6.37 6.36a4 4 0 11-5.66-5.66l7.78-7.78a2 2 0 112.83 2.83l-7.07 7.07a.99.99 0 11-1.41-1.41l7.07-7.07-1.5-1.46z",
  search:
    "M10 2a8 8 0 105.29 14.04l4.33 4.34 1.42-1.42-4.34-4.33A8 8 0 0010 2zm0 2a6 6 0 110 12 6 6 0 010-12z",
  folders:
    "M3 6a2 2 0 012-2h4l2 2h6a2 2 0 012 2v1H3V6zm0 4h18v8a2 2 0 01-2 2H5a2 2 0 01-2-2v-8z",
  undo: "M9 7V3L3 8l6 5V9h6a4 4 0 010 8H8v2h7a6 6 0 000-12H9z",
} as const;

function FeatureCard({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <div className="group rounded-2xl border border-slate-200 bg-white p-6 shadow-card transition hover:-translate-y-0.5 hover:shadow-card-hover">
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
        <Icon path={icon} className="h-6 w-6" />
      </div>
      <h3 className="font-display text-base font-bold tracking-tight text-slate-900">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{body}</p>
    </div>
  );
}

// ---- page -------------------------------------------------------------------------

export default function LandingContent() {
  return (
    <div className="min-h-screen">
      {/* ---------- top nav ---------- */}
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="Meeting Orchestrator logo" className="h-9 w-9 rounded-full object-cover" />
            <span className="font-display text-base font-bold tracking-tight text-slate-900">
              Meeting Orchestrator
            </span>
          </div>
          <nav className="hidden items-center gap-7 text-sm font-medium text-slate-600 md:flex">
            <a href="#how" className="transition hover:text-slate-900">How it works</a>
            <a href="#features" className="transition hover:text-slate-900">Features</a>
            <a href="#stack" className="transition hover:text-slate-900">Tech</a>
          </nav>
          <div className="flex items-center gap-2">
            <Link
              href="/app"
              className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-700 transition hover:text-slate-900 sm:inline-flex"
            >
              Log in
            </Link>
            <Link
              href="/app"
              className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-ink-700"
            >
              Launch app
              <Icon path="M5 12h14M13 6l6 6-6 6" className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </header>

      {/* ---------- hero ---------- */}
      <section className="relative overflow-hidden">
        <div className="mx-auto max-w-6xl px-5 pb-10 pt-16 sm:px-6 sm:pt-24">
          <div className="mx-auto max-w-3xl text-center">
            <h1 className="font-display text-4xl font-bold leading-[1.05] tracking-tight text-slate-900 sm:text-6xl">
              Turn every meeting into a{" "}
              <span className="text-brand-600">tracked action plan</span>.
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-slate-600">
              Drop in a raw transcript, or upload the recording, and an LLM pulls out the decisions,
              assigns each action item to a named owner, and infers deadlines. Everything lands on a live
              Kanban board, with zero manual minute-taking.
            </p>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/app"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-6 py-3 text-sm font-semibold text-white shadow-brand transition hover:bg-brand-700 sm:w-auto"
              >
                Try it now, no sign-up
                <Icon path="M5 12h14M13 6l6 6-6 6" className="h-4 w-4" />
              </Link>
              <a
                href="#how"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50 sm:w-auto"
              >
                See how it works
              </a>
            </div>
            <p className="mt-4 text-xs text-slate-400">
              Continue as a guest, or create an account to keep your boards in sync.
            </p>
          </div>

          {/* ---------- hero visual: a faux Kanban preview ---------- */}
          <div className="relative mx-auto mt-16 max-w-5xl">
            <div className="absolute -inset-x-8 -top-8 -z-10 h-64 rounded-full bg-brand-100/40 blur-3xl" />
            <div className="rounded-2xl border border-slate-200 bg-white/90 p-3 shadow-ink backdrop-blur sm:p-4">
              {/* window chrome */}
              <div className="mb-3 flex items-center gap-1.5 px-1.5">
                <span className="h-3 w-3 rounded-full bg-rose-300" />
                <span className="h-3 w-3 rounded-full bg-amber-300" />
                <span className="h-3 w-3 rounded-full bg-emerald-300" />
                <span className="ml-3 text-xs font-medium text-slate-400">SAP Go-Live · Workshop #4</span>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <BoardColumn
                  title="To Do"
                  accent="bg-slate-400"
                  cards={[
                    { text: "Finalise data-migration cutover plan", owner: "Priya", due: "Jun 28", late: false },
                    { text: "Confirm UAT sign-off owners per module", owner: "Marcus", due: "Jul 02", late: false },
                  ]}
                />
                <BoardColumn
                  title="In Progress"
                  accent="bg-brand-600"
                  cards={[
                    { text: "Draft fallback plan for payroll interface", owner: "Aisha", due: "Jun 24", late: true },
                  ]}
                />
                <BoardColumn
                  title="Done"
                  accent="bg-emerald-500"
                  cards={[
                    { text: "Approve revised go-live date", owner: "Steering", due: "Jun 20", late: false, done: true },
                    { text: "Lock workshop schedule for BU-EMEA", owner: "Lena", due: "Jun 18", late: false, done: true },
                  ]}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- problem strip ---------- */}
      <section className="border-y border-slate-200 bg-white/60">
        <div className="mx-auto grid max-w-6xl grid-cols-1 gap-8 px-5 py-12 sm:grid-cols-3 sm:px-6">
          <Stat figure="31 hrs" label="lost to unproductive meetings each month, per professional" />
          <Stat figure="< 50%" label="of action items are actually followed through on" />
          <Stat figure="0 min" label="spent writing minutes once the transcript is in" />
        </div>
      </section>

      {/* ---------- how it works ---------- */}
      <section id="how" className="mx-auto max-w-6xl px-5 py-20 sm:px-6">
        <SectionHeading
          kicker="How it works"
          title="From raw transcript to tracked board in three steps"
        />
        <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
          <StepCard
            n={1}
            icon={ICONS.doc}
            title="Drop in the meeting"
            body="Paste a raw or messy transcript, or upload an audio/video recording and let Whisper transcribe it for you."
          />
          <StepCard
            n={2}
            icon={ICONS.bolt}
            title="Let the LLM parse it"
            body="The model extracts key decisions, action items, named owners, and deadlines inferred from contextual cues, returned as clean structured data."
          />
          <StepCard
            n={3}
            icon={ICONS.board}
            title="Track it on the board"
            body="Action items appear as cards across To Do, In Progress, and Done. Filter by owner, sort by deadline, and follow up with confidence."
          />
        </div>
      </section>

      {/* ---------- features ---------- */}
      <section id="features" className="border-t border-slate-200 bg-white/60">
        <div className="mx-auto max-w-6xl px-5 py-20 sm:px-6">
          <SectionHeading
            kicker="Features"
            title="Everything you need to close the loop on a meeting"
          />
          <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            <FeatureCard
              icon={ICONS.bolt}
              title="Structured extraction"
              body="Decisions, action items, owners, and deadlines, pulled from the transcript by an LLM and validated before they ever hit the board."
            />
            <FeatureCard
              icon={ICONS.mic}
              title="Speech-to-text"
              body="Upload audio or video and the Whisper pipeline transcribes it end-to-end, so even unrecorded meetings get captured."
            />
            <FeatureCard
              icon={ICONS.board}
              title="Auto-generated Kanban"
              body="Action items organise themselves into To Do, In Progress, and Done. Drag a card to update its status instantly."
            />
            <FeatureCard
              icon={ICONS.checklist}
              title="AI sub-task breakdown"
              body="Turn any action item into a concrete checklist. The assistant suggests the steps, and you tick them off as the work gets done."
            />
            <FeatureCard
              icon={ICONS.bell}
              title="Email deadline reminders"
              body="Opt in per board and get emailed before tasks fall due. Pick how many days' notice, and send yourself a test anytime."
            />
            <FeatureCard
              icon={ICONS.calendar}
              title="Deadline calendar"
              body="Flip to a calendar view to see every action item by its due date, and reschedule by dragging it to a new day."
            />
            <FeatureCard
              icon={ICONS.paperclip}
              title="File attachments"
              body="Attach supporting files like specs, screenshots, and documents directly to a task so the context lives with the work."
            />
            <FeatureCard
              icon={ICONS.share}
              title="Shareable boards"
              body="Send a view-only or edit link to stakeholders. No account required for them to follow along."
            />
            <FeatureCard
              icon={ICONS.shield}
              title="Guest or account"
              body="Start instantly as a guest, then create an account to sync boards across devices and unlock email reminders."
            />
          </div>
        </div>
      </section>

      {/* ---------- tech stack ---------- */}
      <section id="stack" className="mx-auto max-w-6xl px-5 py-20 sm:px-6">
        <SectionHeading kicker="Under the hood" title="Built on a modern full-stack foundation" />
        <div className="mt-10 flex flex-wrap justify-center gap-3">
          {[
            "Next.js / React",
            "FastAPI",
            "LLM API",
            "OpenAI Whisper",
            "PostgreSQL",
            "Tailwind CSS",
            "Pydantic",
            "Docker",
          ].map((t) => (
            <span
              key={t}
              className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-card"
            >
              {t}
            </span>
          ))}
        </div>
      </section>

      {/* ---------- final CTA ---------- */}
      <section className="px-5 pb-20 sm:px-6">
        <div className="mx-auto max-w-5xl overflow-hidden rounded-3xl bg-ink px-8 py-14 text-center shadow-ink sm:px-12">
          <h2 className="font-display text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Stop chasing action items.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-slate-300">
            Turn your next meeting into a board you can actually act on, in seconds.
          </p>
          <Link
            href="/app"
            className="mt-8 inline-flex items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-semibold text-ink shadow-sm transition hover:bg-slate-100"
          >
            Launch the app
            <Icon path="M5 12h14M13 6l6 6-6 6" className="h-4 w-4" />
          </Link>
        </div>
      </section>

      {/* ---------- footer ---------- */}
      <footer className="border-t border-slate-200 bg-white/60">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-5 py-8 text-sm text-slate-500 sm:flex-row sm:px-6">
          <div className="flex items-center gap-2.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="" className="h-6 w-6 rounded-full object-cover" />
            <span className="font-medium text-slate-700">Meeting Orchestrator</span>
          </div>
          <p className="text-xs text-slate-400">
            ICT4011 Capstone Project · AI-Powered Meeting &amp; Workflow Orchestrator
          </p>
        </div>
      </footer>
    </div>
  );
}

// ---- section-local components -----------------------------------------------------

function SectionHeading({ kicker, title }: { kicker: string; title: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="font-display text-sm font-semibold uppercase tracking-wider text-brand-600">{kicker}</p>
      <h2 className="mt-2 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{title}</h2>
    </div>
  );
}

function StepCard({ n, icon, title, body }: { n: number; icon: string; title: string; body: string }) {
  return (
    <div className="relative rounded-2xl border border-slate-200 bg-white p-7 shadow-card">
      <span className="absolute right-6 top-6 font-display text-5xl font-bold text-slate-100">{n}</span>
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-ink text-white">
        <Icon path={icon} className="h-6 w-6" />
      </div>
      <h3 className="font-display text-lg font-bold tracking-tight text-slate-900">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-slate-500">{body}</p>
    </div>
  );
}

function Stat({ figure, label }: { figure: string; label: string }) {
  return (
    <div className="text-center sm:text-left">
      <p className="font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{figure}</p>
      <p className="mt-1 text-sm leading-relaxed text-slate-500">{label}</p>
    </div>
  );
}

type Card = { text: string; owner: string; due: string; late?: boolean; done?: boolean };

function BoardColumn({ title, accent, cards }: { title: string; accent: string; cards: Card[] }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3">
      <div className="mb-2.5 flex items-center gap-2 px-1">
        <span className={`h-2 w-2 rounded-full ${accent}`} />
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</span>
        <span className="ml-auto text-xs font-medium text-slate-400">{cards.length}</span>
      </div>
      <div className="space-y-2">
        {cards.map((c, i) => (
          <div key={i} className="rounded-lg border border-slate-200 bg-white p-3 shadow-card">
            <p className={`text-sm font-medium ${c.done ? "text-slate-400 line-through" : "text-slate-800"}`}>
              {c.text}
            </p>
            <div className="mt-2.5 flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-50 text-[10px] font-bold text-brand-700">
                  {c.owner.slice(0, 1)}
                </span>
                {c.owner}
              </span>
              <span
                className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                  c.late ? "bg-rose-50 text-rose-600" : "bg-slate-100 text-slate-500"
                }`}
              >
                {c.due}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
