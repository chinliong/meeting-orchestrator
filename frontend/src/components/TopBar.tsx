"use client";

import type { Project, User } from "@/lib/types";

interface Props {
  projects: Project[];
  selectedProjectId: number | null;
  onSelectProject: (id: number) => void;
  onNewProject: () => void;
  user: User | null;
  onLogin: () => void;
  onLogout: () => void;
}

export default function TopBar({
  projects,
  selectedProjectId,
  onSelectProject,
  onNewProject,
  user,
  onLogin,
  onLogout,
}: Props) {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm">
            {/* sparkle / AI mark */}
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
              <path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2z" />
            </svg>
          </div>
          <div className="leading-tight">
            <h1 className="text-base font-semibold text-slate-900">Meeting Orchestrator</h1>
            <p className="text-xs text-slate-500">AI action items from meeting transcripts</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {projects.length > 0 && (
            <div className="relative">
              <select
                value={selectedProjectId ?? ""}
                onChange={(e) => onSelectProject(Number(e.target.value))}
                className="appearance-none rounded-lg border border-slate-300 bg-white py-2 pl-3 pr-9 text-sm font-medium text-slate-700 outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <svg
                viewBox="0 0 20 20"
                className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
          )}
          <button
            onClick={onNewProject}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
              <path d="M10 4a1 1 0 011 1v4h4a1 1 0 110 2h-4v4a1 1 0 11-2 0v-4H5a1 1 0 110-2h4V5a1 1 0 011-1z" />
            </svg>
            New project
          </button>

          <div className="ml-1 flex items-center gap-2 border-l border-slate-200 pl-3">
            {user ? (
              <>
                <span className="hidden text-sm text-slate-500 sm:inline" title={user.email}>
                  {user.email}
                </span>
                <button
                  onClick={onLogout}
                  className="rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50"
                >
                  Sign out
                </button>
              </>
            ) : (
              <>
                <span className="hidden text-sm text-slate-400 sm:inline">Guest</span>
                <button
                  onClick={onLogin}
                  className="rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-50"
                >
                  Sign in / Save
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
