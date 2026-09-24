"use client";

import { useEffect, useRef, useState } from "react";

import type { Project } from "@/lib/types";

interface Props {
  /** The boards the cross-board view can include: the signed-in user's own. */
  projects: Project[];
  /** True while the cross-board view is showing. */
  active: boolean;
  /** The boards included in the cross-board view; null means all of them. */
  selected: number[] | null;
  onThisProject: () => void;
  onActivate: () => void;
  onChange: (ids: number[] | null) => void;
}

/**
 * The "This project | All projects" toggle. Once the cross-board view is on, the second button
 * opens a checklist to narrow it to some boards; its label then reads e.g. "3 projects".
 */
export default function ProjectScopePicker({
  projects,
  active,
  selected,
  onThisProject,
  onActivate,
  onChange,
}: Props) {
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

  const chosen = selected ?? projects.map((p) => p.id);
  const count = projects.filter((p) => chosen.includes(p.id)).length;
  const label =
    selected === null || count === projects.length ? "All projects" : `${count} project${count === 1 ? "" : "s"}`;

  const toggle = (id: number) => {
    const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
    if (next.length === 0) return; // the view always includes at least one board
    onChange(next.length >= projects.length ? null : next);
  };

  return (
    <div ref={containerRef} className="relative flex shrink-0 rounded-lg bg-slate-900/[0.05] p-1 text-sm font-medium">
      <button
        onClick={() => {
          setOpen(false);
          onThisProject();
        }}
        className={`rounded-md px-3 py-1 transition ${
          active ? "text-slate-500 hover:text-slate-700" : "bg-ink text-white shadow-sm"
        }`}
      >
        This project
      </button>
      <button
        onClick={() => (active ? setOpen((v) => !v) : onActivate())}
        aria-haspopup="true"
        aria-expanded={open}
        title={active ? "Choose which projects to show" : "Show tasks from all your projects"}
        className={`inline-flex items-center gap-1 rounded-md py-1 pl-3 pr-2 transition ${
          active ? "bg-ink text-white shadow-sm" : "text-slate-500 hover:text-slate-700"
        }`}
      >
        {label}
        <svg
          viewBox="0 0 20 20"
          className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`}
          fill="currentColor"
          aria-hidden
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-40 mt-2 w-72 max-w-[calc(100vw-2rem)] rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
          <div className="flex items-center justify-between px-2 pb-1.5 pt-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Show tasks from</span>
            <button
              onClick={() => onChange(null)}
              disabled={count === projects.length}
              className="text-xs font-medium text-brand-600 hover:underline disabled:cursor-default disabled:text-slate-300 disabled:no-underline"
            >
              Select all
            </button>
          </div>
          <ul className="max-h-64 overflow-y-auto">
            {projects.map((p) => {
              const on = chosen.includes(p.id);
              const last = on && count === 1;
              return (
                <li key={p.id}>
                  <label
                    title={last ? "At least one project stays selected" : undefined}
                    className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 font-normal ${
                      last ? "cursor-not-allowed" : "cursor-pointer hover:bg-slate-50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={last}
                      onChange={() => toggle(p.id)}
                      className="h-4 w-4 shrink-0 rounded border-slate-300 accent-[#0E1626]"
                    />
                    <span className="truncate text-slate-700">{p.name}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
