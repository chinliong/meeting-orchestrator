"use client";

/** Shown while the app starts and the server wakes from sleep. */
export function LoadingScreen({ slow }: { slow: boolean }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5 px-6 text-center">
      <div className="relative flex items-center justify-center">
        <span className="absolute h-16 w-16 animate-ping rounded-full bg-slate-300/40" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/logo.png"
          alt="Meeting Orchestrator"
          className="relative h-14 w-14 rounded-full object-cover shadow-card"
        />
      </div>

      <div className="flex items-center gap-2 text-slate-600">
        <svg className="h-4 w-4 animate-spin text-slate-400" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
        <span className="text-sm font-medium">Loading your boards…</span>
      </div>

      {slow && (
        <p className="max-w-sm text-xs leading-relaxed text-slate-400">
          Waking up the server — the free hosting tier sleeps after inactivity, so the first load
          can take up to a minute.
        </p>
      )}
    </div>
  );
}

/** Shown to a signed-in user with no boards yet. */
export function EmptyProjects({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-card">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-slate-900">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor">
          <path d="M3 6a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V6z" />
        </svg>
      </div>
      <h2 className="text-lg font-semibold text-slate-900">No projects yet</h2>
      <p className="mt-1 text-sm text-slate-500">
        Create a project to start turning meeting transcripts into tracked action items.
      </p>
      <button
        onClick={onCreate}
        className="mt-5 inline-flex items-center gap-1.5 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700"
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
        </svg>
        Create your first project
      </button>
    </div>
  );
}
