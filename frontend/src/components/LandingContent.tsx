import Link from "next/link";

// The marketing landing UI. Rendered both at /landing (direct) and at / for
// first-time visitors via the entry gate in app/page.tsx.
//
// Styled in the app's own voice so the site and the product read as one: Space Grotesk headings,
// the navy "ink" panel with its concentric-arc motif, white cards on the soft enterprise ground,
// and real screenshots of the board (public/landing/*.webp) in place of illustrations.

function Arrow({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={className} fill="currentColor" aria-hidden>
      <path d="M3 10a.75.75 0 01.75-.75h10.64l-4.2-3.96a.75.75 0 111.03-1.08l5.5 5.25a.75.75 0 010 1.08l-5.5 5.25a.75.75 0 11-1.03-1.08l4.2-3.96H3.75A.75.75 0 013 10z" />
    </svg>
  );
}

/** The app's concentric-arc ornament (as on the stat cards), tinted by `tone`. */
function Arcs({ tone, className = "" }: { tone: string; className?: string }) {
  return (
    <span aria-hidden className={`pointer-events-none absolute ${tone} ${className}`}>
      <span
        className="absolute -bottom-7 -right-7 h-[5.5rem] w-[5.5rem] rounded-full border-2 opacity-[0.16]"
        style={{ borderColor: "currentColor" }}
      />
      <span
        className="absolute -bottom-3.5 -right-3.5 h-14 w-14 rounded-full border-2 opacity-[0.26]"
        style={{ borderColor: "currentColor" }}
      />
    </span>
  );
}

/** The navy panel of the app's "New meeting" card: arcs in the corner and a soft brand wash. */
function InkPanel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`relative overflow-hidden rounded-3xl bg-ink text-slate-100 shadow-ink ${className}`}>
      <span className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full border border-white/15" />
      <span className="pointer-events-none absolute -right-6 -top-6 h-32 w-32 rounded-full border border-white/10" />
      <span
        className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(520px 260px at 108% -10%, rgba(37,99,217,.24) 0%, transparent 62%)" }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-display text-sm font-semibold uppercase tracking-wider text-brand-600">{children}</p>
  );
}

export default function LandingContent() {
  return (
    <div className="min-h-screen">
      {/* ---------- nav (the app's top bar) ---------- */}
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3 sm:px-6">
          <a href="#top" className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="Meeting Orchestrator logo" className="h-9 w-9 rounded-full object-cover" />
            <span className="font-display text-[17px] font-bold tracking-tight text-slate-900">Meeting Orchestrator</span>
          </a>
          <nav className="hidden items-center gap-7 text-sm font-medium text-slate-600 md:flex">
            <a href="#how" className="transition hover:text-slate-900">How it works</a>
            <a href="#features" className="transition hover:text-slate-900">Features</a>
            <a href="#accuracy" className="transition hover:text-slate-900">Accuracy</a>
          </nav>
          <div className="flex items-center gap-2">
            <Link
              href="/app"
              className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-700 transition hover:text-slate-900 sm:inline-flex"
            >
              Sign in
            </Link>
            <Link
              href="/app"
              className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-ink-700"
            >
              Open app
              <Arrow />
            </Link>
          </div>
        </div>
      </header>

      <main id="top">
        {/* ---------- hero ---------- */}
        <section className="px-5 pt-16 text-center sm:px-6 sm:pt-24">
          <Kicker>Meeting Orchestrator</Kicker>
          <h1 className="mx-auto mt-3 max-w-4xl font-display text-5xl font-bold leading-[1.02] tracking-tight text-slate-900 sm:text-7xl">
            Meetings in.
            <br />
            <span className="text-brand-600">Action out.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-slate-600 sm:text-xl">
            Paste a transcript or upload a recording. Every action item lands on a board, with an owner
            and a deadline.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/app"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-ink px-6 py-3 font-display text-[15px] font-semibold text-white shadow-ink transition hover:bg-ink-700 sm:w-auto"
            >
              Try it free
              <Arrow />
            </Link>
            <a
              href="#how"
              className="inline-flex w-full items-center justify-center rounded-xl bg-white px-6 py-3 font-display text-[15px] font-semibold text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50 sm:w-auto"
            >
              See how it works
            </a>
          </div>
          <p className="mt-4 text-sm text-slate-500">No sign-up needed. Create an account whenever you like.</p>

          <div className="mx-auto mt-14 max-w-[1180px] sm:mt-20">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/landing/board.webp"
              width={2400}
              height={1500}
              alt="The Meeting Orchestrator board, with tasks from two meetings sorted into To Do, In Progress and Done"
              className="w-full rounded-2xl border border-slate-200 shadow-ink sm:rounded-3xl"
            />
          </div>
        </section>

        {/* ---------- statement ---------- */}
        <section className="mx-auto max-w-6xl px-5 py-24 sm:px-6">
          <InkPanel className="px-8 py-14 sm:px-14 sm:py-20">
            <p className="max-w-3xl font-display text-[26px] font-bold leading-[1.25] tracking-tight text-slate-400 sm:text-[36px]">
              Every meeting ends with promises: who will do what, and by when.{" "}
              <span className="text-white">
                Meeting Orchestrator writes them down for you, and keeps them where the whole team can
                see them.
              </span>
            </p>
          </InkPanel>
        </section>

        {/* ---------- how it works ---------- */}
        <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-5 pb-24 sm:px-6">
          <div className="mx-auto max-w-2xl text-center">
            <Kicker>How it works</Kicker>
            <h2 className="mt-2 font-display text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
              Three steps. No minutes.
            </h2>
          </div>
          <div className="mt-14 grid grid-cols-1 gap-5 md:grid-cols-3">
            <Step
              n="01"
              tone="text-brand"
              dot="bg-brand"
              title="Capture"
              body="Paste the transcript, messy or not. Or upload the audio or video recording, up to 500 MB, and it is transcribed for you."
            />
            <Step
              n="02"
              tone="text-amber-400"
              dot="bg-amber-400"
              title="Extract"
              body="Each action item is pulled out with its owner and a deadline worked out from cues like “by Friday”, and linked to the decision it came from."
            />
            <Step
              n="03"
              tone="text-emerald-500"
              dot="bg-emerald-500"
              title="Track"
              body="Tasks appear on a board in To Do, In Progress and Done. Drag a card to move it. Filter by owner. Sort by deadline."
            />
          </div>
        </section>

        {/* ---------- features ---------- */}
        <section id="features" className="scroll-mt-20 border-y border-slate-200 bg-white/60">
          <div className="mx-auto max-w-6xl px-5 py-24 sm:px-6">
            <div className="mx-auto max-w-2xl text-center">
              <Kicker>Features</Kicker>
              <h2 className="mt-2 font-display text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
                Everything after the meeting.
              </h2>
            </div>

            <div className="mt-14 grid grid-cols-1 gap-5 md:grid-cols-2">
              <Tile
                title="Big tasks, broken down"
                body="Turn any task into a checklist, suggested from the task itself or from your own instructions. Attach the files it needs."
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/landing/task.webp"
                  width={1024}
                  height={1548}
                  loading="lazy"
                  alt="A task opened with its subtask checklist and an attached file"
                  className="mx-auto w-[82%] rounded-t-2xl border border-b-0 border-slate-200 shadow-card-hover"
                />
              </Tile>
              <Tile
                title="Right there on your phone"
                body="The whole board works on a small screen, so you can check what is due on the way to the next meeting."
              >
                <PhoneFrame src="/landing/phone.webp" width={1320} height={2868} alt="The board on a phone" />
              </Tile>
            </div>

            <div className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card md:grid md:grid-cols-[2fr_3fr]">
              <div className="p-8 sm:p-10">
                <h3 className="font-display text-2xl font-bold tracking-tight text-slate-900">The month, at a glance</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-slate-500">
                  Switch to the calendar to see every task on its due date. Drag one to another day to
                  reschedule it.
                </p>
              </div>
              <div className="relative h-72 md:h-auto md:min-h-[360px]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/landing/calendar.webp"
                  width={1600}
                  height={1421}
                  loading="lazy"
                  alt="The calendar view for October, with tasks on their due dates"
                  className="absolute bottom-0 left-8 right-0 top-0 h-full w-[calc(100%-2rem)] rounded-tl-2xl border-l border-t border-slate-200 object-cover object-left-top shadow-card-hover md:left-0 md:top-10 md:h-[calc(100%-2.5rem)] md:w-full"
                />
              </div>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
              <SmallTile dot="bg-brand" title="Recordings, transcribed" body="Upload audio or video and it is turned into a transcript first." />
              <SmallTile dot="bg-amber-400" title="Share with a link" body="Send a view-only or an edit link. No account needed to open it." />
              <SmallTile dot="bg-emerald-500" title="Reminders by email" body="Choose which boards remind you, and how many days before a deadline." />
              <SmallTile dot="bg-rose-500" title="Undo anything" body="Moved, edited or deleted something by mistake? Undo puts it back." />
            </div>
          </div>
        </section>

        {/* ---------- accuracy (in the app's stat-card style) ---------- */}
        <section id="accuracy" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-24 sm:px-6">
          <div className="mx-auto max-w-2xl text-center">
            <Kicker>Accuracy</Kicker>
            <h2 className="mt-2 font-display text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
              Accurate where it counts.
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-lg leading-relaxed text-slate-600">
              Tested against meeting transcripts with a known list of action items.
            </p>
          </div>
          <div className="mt-14 grid grid-cols-1 gap-5 sm:grid-cols-3">
            <Figure dot="bg-brand" tone="text-brand" label="Precision" value="96%" body="of the tasks it proposes are real action items." />
            <Figure dot="bg-amber-400" tone="text-amber-400" label="Deadlines" value="96%" body="of deadlines it sets fall on exactly the right date." />
            <Figure dot="bg-emerald-500" tone="text-emerald-500" label="Valid output" value="100%" body="of results came back complete and in the right format." />
          </div>
          <p className="mt-5 text-center text-sm text-slate-500">
            Measured with Gemini Flash on eight annotated meeting transcripts, eight runs each.
          </p>
        </section>

        {/* ---------- closing ---------- */}
        <section className="mx-auto max-w-6xl px-5 pb-24 sm:px-6">
          <InkPanel className="px-8 py-16 text-center sm:px-12">
            <h2 className="font-display text-4xl font-bold tracking-tight text-white sm:text-5xl">
              Your next meeting, handled.
            </h2>
            <p className="mx-auto mt-4 max-w-md text-base leading-relaxed text-slate-400">
              Start as a guest in seconds, or sign in to keep your boards.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/app"
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 font-display text-[15px] font-semibold text-ink shadow-sm transition hover:bg-slate-100"
              >
                Try it free
                <Arrow />
              </Link>
              <Link
                href="/app"
                className="inline-flex items-center justify-center rounded-xl px-6 py-3 font-display text-[15px] font-semibold text-slate-200 ring-1 ring-white/20 transition hover:bg-white/10"
              >
                Sign in
              </Link>
            </div>
          </InkPanel>
        </section>
      </main>

      {/* ---------- footer ---------- */}
      <footer className="border-t border-slate-200 bg-white/60 px-5 py-8 text-xs text-slate-500 sm:px-6">
        <div className="mx-auto max-w-6xl leading-relaxed">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2.5">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.png" alt="" className="h-6 w-6 rounded-full object-cover" />
              <span className="font-display text-sm font-semibold text-slate-700">Meeting Orchestrator</span>
            </div>
            <p>Built with Next.js, FastAPI, PostgreSQL, Gemini Flash and Deepgram Nova-3.</p>
            <p>ICT4011 Capstone Project · AI-Powered Meeting &amp; Workflow Orchestrator</p>
          </div>
        </div>
      </footer>
    </div>
  );
}

// ---- section components -----------------------------------------------------------

function Step({ n, tone, dot, title, body }: { n: string; tone: string; dot: string; title: string; body: string }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-7 shadow-card">
      <Arcs tone={tone} className="bottom-0 right-0" />
      <div className="relative flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        <span className="font-display text-xs font-semibold uppercase tracking-wide text-slate-500">Step {n}</span>
      </div>
      <h3 className="relative mt-3 font-display text-2xl font-bold tracking-tight text-slate-900">{title}</h3>
      <p className="relative mt-2 text-[15px] leading-relaxed text-slate-500">{body}</p>
    </div>
  );
}

function Tile({ title, body, children }: { title: string; body: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
      <div className="px-8 pt-10 text-center sm:px-10">
        <h3 className="font-display text-2xl font-bold tracking-tight text-slate-900">{title}</h3>
        <p className="mx-auto mt-3 max-w-sm text-[15px] leading-relaxed text-slate-500">{body}</p>
      </div>
      {/* The visual is cut off by the bottom edge of the tile, as if rising into view. */}
      <div className="mt-10 h-80 overflow-hidden bg-slate-50 pt-6 sm:h-96">{children}</div>
    </div>
  );
}

function SmallTile({ dot, title, body }: { dot: string; title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
      <span className={`block h-2 w-2 rounded-full ${dot}`} />
      <h3 className="mt-3 font-display text-lg font-bold tracking-tight text-slate-900">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{body}</p>
    </div>
  );
}

function Figure({
  dot,
  tone,
  label,
  value,
  body,
}: {
  dot: string;
  tone: string;
  label: string;
  value: string;
  body: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
      <Arcs tone={tone} className="bottom-0 right-0" />
      <div className="relative flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        <span className="font-display text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      </div>
      <p className="relative mt-3 font-display text-5xl font-bold tracking-tight text-slate-900">{value}</p>
      <p className="relative mt-2 max-w-[15rem] text-[15px] leading-snug text-slate-500">{body}</p>
    </div>
  );
}

/**
 * A modern Pro Max-style phone drawn in CSS (titanium band, black bezel, Dynamic Island, side
 * buttons and a 9:41 status bar) around a screenshot captured at a 440 x 956 point screen. Drawn
 * rather than using a manufacturer's device artwork. Every part is sized in container units
 * (cqw, a percentage of the frame's width), so the island, status bar and corners keep their
 * proportions however small the frame is drawn, e.g. on a phone.
 */
function PhoneFrame({ src, width, height, alt }: { src: string; width: number; height: number; alt: string }) {
  return (
    <div className="relative mx-auto w-[60%] max-w-[270px] [container-type:inline-size]">
      <span aria-hidden className="absolute -left-[1.1cqw] top-[15%] h-[9cqw] w-[1.1cqw] rounded-l-sm bg-[#3b3b40]" />
      <span aria-hidden className="absolute -left-[1.1cqw] top-[24%] h-[15cqw] w-[1.1cqw] rounded-l-sm bg-[#3b3b40]" />
      <span aria-hidden className="absolute -left-[1.1cqw] top-[33%] h-[15cqw] w-[1.1cqw] rounded-l-sm bg-[#3b3b40]" />
      <span aria-hidden className="absolute -right-[1.1cqw] top-[26%] h-[20cqw] w-[1.1cqw] rounded-r-sm bg-[#3b3b40]" />
      <div className="rounded-[17.5cqw] bg-gradient-to-b from-[#5b5b61] via-[#2e2e33] to-[#1d1d20] p-[1.1cqw] shadow-ink">
        <div className="rounded-[16.4cqw] bg-black p-[2.6cqw]">
          <div className="relative overflow-hidden rounded-[13.8cqw] bg-white">
            <div className="flex h-[11.5cqw] items-center justify-between px-[8cqw] pt-[1cqw] text-[4.1cqw] font-semibold leading-none text-slate-900">
              <span>9:41</span>
              <span className="flex items-center gap-[1.3cqw]" aria-hidden>
                <svg viewBox="0 0 18 12" className="h-[3cqw] w-[4.5cqw]" fill="currentColor">
                  <rect x="0" y="8" width="3" height="4" rx="1" />
                  <rect x="5" y="5.5" width="3" height="6.5" rx="1" />
                  <rect x="10" y="3" width="3" height="9" rx="1" />
                  <rect x="15" y="0" width="3" height="12" rx="1" />
                </svg>
                <svg viewBox="0 0 16 12" className="h-[3cqw] w-[4cqw]" fill="currentColor">
                  <path d="M8 2.2c2.3 0 4.4.9 6 2.4l1.1-1.2A10.2 10.2 0 008 .5 10.2 10.2 0 00.9 3.4L2 4.6a8.5 8.5 0 016-2.4zm0 3.4c1.4 0 2.6.5 3.6 1.4l1.1-1.2A6.9 6.9 0 008 3.9a6.9 6.9 0 00-4.7 1.9L4.4 7A5.2 5.2 0 018 5.6zm0 3.3c.5 0 1 .2 1.3.5L8 10.8 6.7 9.4c.3-.3.8-.5 1.3-.5z" />
                </svg>
                <span className="relative flex h-[3.4cqw] w-[6.8cqw] items-center rounded-[1cqw] border border-slate-900/40 p-[0.5cqw]">
                  <span className="h-full w-[78%] rounded-[0.5cqw] bg-slate-900" />
                  <span className="absolute -right-[1cqw] top-1/2 h-[1.3cqw] w-[0.5cqw] -translate-y-1/2 rounded-r bg-slate-900/40" />
                </span>
              </span>
            </div>
            <span aria-hidden className="absolute left-1/2 top-[2.6cqw] h-[8cqw] w-[28cqw] -translate-x-1/2 rounded-full bg-black" />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={src} width={width} height={height} loading="lazy" alt={alt} className="block w-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
