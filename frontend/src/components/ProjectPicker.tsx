"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Project } from "@/lib/types";

interface Props {
  projects: Project[];
  selectedProjectId: number | null;
  onSelect: (id: number) => void;
}

/** A searchable project dropdown (type-to-filter), replacing the native select. */
export default function ProjectPicker({ projects, selectedProjectId, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = projects.find((p) => p.id === selectedProjectId) ?? null;

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
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const choose = (id: number) => {
    onSelect(id);
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
        <span className="flex-1 truncate text-left">{selected?.name ?? "Select project"}</span>
        <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-400" fill="currentColor">
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 z-40 mt-1 w-72 max-w-[calc(100vw_-_2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg sm:left-auto sm:right-0">
          <div className="border-b border-slate-100 p-2">
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setHighlight(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Search projects..."
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </div>
          <ul className="max-h-72 overflow-y-auto p-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-6 text-center text-sm text-slate-400">No projects match</li>
            ) : (
              filtered.map((p, i) => {
                const isSelected = p.id === selectedProjectId;
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
                          <path
                            fillRule="evenodd"
                            d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0l-3.5-3.5a1 1 0 011.4-1.4l2.8 2.79 6.8-6.79a1 1 0 011.4 0z"
                            clipRule="evenodd"
                          />
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
