"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Project } from "@/lib/types";

/** The multi-project view, offered to signed-in users who own more than one board. */
export interface ProjectScope {
  /** The boards the multi-project view can include: the user's own. */
  ownedIds: number[];
  /** True while several projects are shown instead of one. */
  active: boolean;
  /** The boards shown in the multi-project view; null means all of them. */
  selected: number[] | null;
  onShowAll: () => void;
  onShowSome: (ids: number[]) => void;
}

interface Props {
  projects: Project[];
  selectedProjectId: number | null;
  onSelect: (id: number) => void;
  scope?: ProjectScope;
}

const CHECK = "M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0l-3.5-3.5a1 1 0 011.4-1.4l2.8 2.79 6.8-6.79a1 1 0 011.4 0z";

/**
 * A searchable project dropdown (type-to-filter), replacing the native select. With `scope`, it
 * is also where several projects are chosen: "All projects", or "Choose projects…" to tick some.
 */
export default function ProjectPicker({ projects, selectedProjectId, onSelect, scope }: Props) {
  const [open, setOpen] = useState(false);
  const [choosing, setChoosing] = useState(false); // the "Choose projects…" checklist
  const [draft, setDraft] = useState<number[]>([]);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = projects.find((p) => p.id === selectedProjectId) ?? null;
  const multi = scope && scope.ownedIds.length > 1 ? scope : undefined;
  const ownedProjects = multi ? projects.filter((p) => multi.ownedIds.includes(p.id)) : [];
  const shownCount = multi ? (multi.selected ?? multi.ownedIds).filter((id) => multi.ownedIds.includes(id)).length : 0;
  const showingAll = !!multi?.active && shownCount === multi.ownedIds.length;
  const label = multi?.active
    ? showingAll
      ? "All projects"
      : `${shownCount} project${shownCount === 1 ? "" : "s"}`
    : selected?.name ?? "Select project";

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? projects.filter((p) => p.name.toLowerCase().includes(q)) : projects;
  }, [projects, query]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Reset and focus the search field each time the menu opens.
  useEffect(() => {
    if (open) {
      setQuery("");
      setHighlight(0);
      setChoosing(false);
      // Focus the search so typing filters straight away, but not on touch screens, where it
      // would pop up the keyboard over the menu every time it opens.
      if (window.matchMedia("(hover: hover)").matches) {
        requestAnimationFrame(() => inputRef.current?.focus());
      }
    }
  }, [open]);

  const choose = (id: number) => {
    onSelect(id);
    setOpen(false);
  };

  const startChoosing = () => {
    if (!multi) return;
    setDraft(multi.active ? (multi.selected ?? multi.ownedIds) : multi.ownedIds);
    setChoosing(true);
  };

  const applyChoice = () => {
    if (!multi || draft.length === 0) return;
    // One project is just that project, with its normal board (and the New meeting panel).
    if (draft.length === 1) return choose(draft[0]);
    if (draft.length >= multi.ownedIds.length) multi.onShowAll();
    else multi.onShowSome(draft);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[highlight]) choose(filtered[highlight].id);
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex min-w-[120px] max-w-[160px] items-center gap-2 rounded-lg border border-slate-300 bg-white py-2 pl-3 pr-2 text-sm font-medium text-slate-700 outline-none transition hover:bg-slate-50 focus:border-brand focus:ring-2 focus:ring-brand/20 sm:max-w-[260px]"
      >
        <span className="flex-1 truncate text-left">{label}</span>
        <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-400" fill="currentColor">
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && choosing && multi && (
        <div className="absolute left-0 z-40 mt-1 w-72 max-w-[calc(100vw_-_2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg sm:left-auto sm:right-0">
          <div className="flex items-center justify-between border-b border-slate-100 px-2 py-2">
            <button
              type="button"
              onClick={() => setChoosing(false)}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-sm font-medium text-slate-600 hover:bg-slate-100"
            >
              <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
                <path fillRule="evenodd" d="M12.8 4.2a.75.75 0 010 1.06L8.06 10l4.74 4.74a.75.75 0 11-1.06 1.06l-5.27-5.27a.75.75 0 010-1.06l5.27-5.27a.75.75 0 011.06 0z" clipRule="evenodd" />
              </svg>
              Choose projects
            </button>
            <button
              type="button"
              onClick={() => setDraft(multi.ownedIds)}
              disabled={draft.length === multi.ownedIds.length}
              className="px-1.5 text-xs font-medium text-brand-600 hover:underline disabled:cursor-default disabled:text-slate-300 disabled:no-underline"
            >
              Select all
            </button>
          </div>
          <ul className="max-h-72 overflow-y-auto p-1">
            {ownedProjects.map((p) => {
              const on = draft.includes(p.id);
              return (
                <li key={p.id}>
                  <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => setDraft((d) => (on ? d.filter((x) => x !== p.id) : [...d, p.id]))}
                      className="h-4 w-4 shrink-0 rounded border-slate-300 accent-[#0E1626]"
                    />
                    <span className="truncate">{p.name}</span>
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="border-t border-slate-100 p-2">
            <button
              type="button"
              onClick={applyChoice}
              disabled={draft.length === 0}
              className="w-full rounded-lg bg-ink px-3 py-2 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:opacity-40"
            >
              {draft.length === 0
                ? "Choose at least one project"
                : draft.length >= multi.ownedIds.length
                  ? "Show all projects"
                  : draft.length === 1
                    ? "Open this project"
                    : `Show ${draft.length} projects`}
            </button>
          </div>
        </div>
      )}

      {open && !choosing && (
        <div className="absolute left-0 z-40 mt-1 w-72 max-w-[calc(100vw_-_2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg sm:left-auto sm:right-0">
          {/* A plain search row, as in a command menu: an icon and the text, no box around it. */}
          <div className="flex items-center gap-2 border-b border-slate-100 px-3">
            <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-400" fill="currentColor" aria-hidden>
              <path
                fillRule="evenodd"
                d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.45 4.39l3.33 3.33a.75.75 0 11-1.06 1.06l-3.33-3.33A7 7 0 012 9z"
                clipRule="evenodd"
              />
            </svg>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setHighlight(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Search projects"
              aria-label="Search projects"
              className="w-full bg-transparent py-2.5 text-sm text-slate-800 outline-none placeholder:text-slate-400"
            />
            {query && (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setHighlight(0);
                  inputRef.current?.focus();
                }}
                aria-label="Clear search"
                className="shrink-0 rounded p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
              >
                <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
                  <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                </svg>
              </button>
            )}
          </div>
          {multi && !query.trim() && (
            <ul className="border-b border-slate-100 p-1">
              <li>
                <button
                  type="button"
                  onClick={() => {
                    multi.onShowAll();
                    setOpen(false);
                  }}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-slate-100 ${
                    showingAll ? "font-medium text-slate-900" : "text-slate-700"
                  }`}
                >
                  <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-400" fill="currentColor" aria-hidden>
                    <path d="M3 4.5A1.5 1.5 0 014.5 3h3A1.5 1.5 0 019 4.5v3A1.5 1.5 0 017.5 9h-3A1.5 1.5 0 013 7.5v-3zm8 0A1.5 1.5 0 0112.5 3h3A1.5 1.5 0 0117 4.5v3A1.5 1.5 0 0115.5 9h-3A1.5 1.5 0 0111 7.5v-3zm-8 8A1.5 1.5 0 014.5 11h3A1.5 1.5 0 019 12.5v3A1.5 1.5 0 017.5 17h-3A1.5 1.5 0 013 15.5v-3zm8 0a1.5 1.5 0 011.5-1.5h3a1.5 1.5 0 011.5 1.5v3a1.5 1.5 0 01-1.5 1.5h-3a1.5 1.5 0 01-1.5-1.5v-3z" />
                  </svg>
                  <span className="flex-1">All projects</span>
                  {showingAll && (
                    <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-900" fill="currentColor">
                      <path fillRule="evenodd" d={CHECK} clipRule="evenodd" />
                    </svg>
                  )}
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={startChoosing}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-slate-100 ${
                    multi.active && !showingAll ? "font-medium text-slate-900" : "text-slate-700"
                  }`}
                >
                  <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-400" fill="currentColor" aria-hidden>
                    <path fillRule="evenodd" d="M4 3a1 1 0 00-1 1v3a1 1 0 001 1h3a1 1 0 001-1V4a1 1 0 00-1-1H4zm.5 2.9l.9.9 1.6-1.6.7.7-2.3 2.3-1.6-1.6.7-.7zM10 5.25a.75.75 0 01.75-.75h5.5a.75.75 0 010 1.5h-5.5a.75.75 0 01-.75-.75zM4 12a1 1 0 00-1 1v3a1 1 0 001 1h3a1 1 0 001-1v-3a1 1 0 00-1-1H4zm.5 1.5h2v2h-2v-2zm5.5.75a.75.75 0 01.75-.75h5.5a.75.75 0 010 1.5h-5.5a.75.75 0 01-.75-.75z" clipRule="evenodd" />
                  </svg>
                  <span className="flex-1">Choose projects…</span>
                  {multi.active && !showingAll ? (
                    <span className="text-xs text-slate-400">
                      {shownCount} of {multi.ownedIds.length}
                    </span>
                  ) : (
                    <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-300" fill="currentColor" aria-hidden>
                      <path fillRule="evenodd" d="M7.2 4.2a.75.75 0 011.06 0l5.27 5.27a.75.75 0 010 1.06L8.26 15.8a.75.75 0 11-1.06-1.06L11.94 10 7.2 5.26a.75.75 0 010-1.06z" clipRule="evenodd" />
                    </svg>
                  )}
                </button>
              </li>
            </ul>
          )}
          {multi && !query.trim() && (
            <p className="px-4 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Projects</p>
          )}
          <ul className="max-h-72 overflow-y-auto p-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-6 text-center text-sm text-slate-400">No projects match</li>
            ) : (
              filtered.map((p, i) => {
                const isSelected = !multi?.active && p.id === selectedProjectId;
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => choose(p.id)}
                      onMouseEnter={() => setHighlight(i)}
                      className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition ${
                        i === highlight ? "bg-slate-100" : ""
                      } ${isSelected ? "font-medium text-slate-900" : "text-slate-700"}`}
                    >
                      <span className="flex-1 truncate">{p.name}</span>
                      {isSelected && (
                        <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-900" fill="currentColor">
                          <path fillRule="evenodd" d={CHECK} clipRule="evenodd" />
                        </svg>
                      )}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
