"use client";

import { useEffect, useRef, useState } from "react";

import { avatarColor, initials } from "@/lib/format";

interface Props {
  owners: string[];
  /** Tasks per owner among the tasks on screen, shown beside each name. */
  counts: Record<string, number>;
  /** The chosen owners; empty for everyone. */
  selected: string[];
  onChange: (owners: string[]) => void;
}

/**
 * The owner filter as a dropdown beside the Meeting filter, so the Filter row stays on one line
 * however many people a board has. Several owners can be ticked at once, and the list stays open
 * while ticking; "All owners" clears the choice. Each owner is listed with their avatar and task
 * count. On a phone the list opens as a sheet along the bottom of the screen, as the Meeting filter
 * does.
 */
export default function OwnerFilter({ owners, counts, selected, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = (owner: string) =>
    onChange(selected.includes(owner) ? selected.filter((o) => o !== owner) : [...selected, owner]);
  const any = selected.length > 0;
  const label = !any ? "All owners" : selected.length === 1 ? selected[0] : `${selected[0]} +${selected.length - 1}`;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={any ? `Showing tasks for ${selected.join(", ")}` : "Filter by owner"}
        className={`inline-flex max-w-[16rem] items-center gap-1.5 rounded-full py-1 pl-1.5 pr-2 text-sm font-medium transition ${
          any ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-900/5"
        }`}
      >
        {any ? (
          // The first two chosen owners' avatars, overlapping.
          <span className="flex shrink-0 -space-x-1">
            {selected.slice(0, 2).map((o) => (
              <span
                key={o}
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[9.5px] font-semibold ring-2 ring-slate-900 ${avatarColor(o)}`}
              >
                {initials(o)}
              </span>
            ))}
          </span>
        ) : (
          <svg viewBox="0 0 20 20" className="ml-1 h-4 w-4 shrink-0 opacity-70" fill="currentColor" aria-hidden>
            <path d="M10 9a3 3 0 100-6 3 3 0 000 6zM3.5 16.2A6.5 6.5 0 0116.5 16.2a.8.8 0 01-.7 1.2H4.2a.8.8 0 01-.7-1.2z" />
          </svg>
        )}
        <span className="truncate">{label}</span>
        {!any && <span className="text-slate-400">{owners.length}</span>}
        <svg viewBox="0 0 20 20" className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} fill="currentColor" aria-hidden>
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        // On a phone the list opens as a sheet along the bottom of the screen; from sm up it is a dropdown.
        <div
          role="listbox"
          aria-label="Filter by owner"
          aria-multiselectable="true"
          className="fixed inset-x-4 bottom-4 z-40 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl sm:absolute sm:inset-x-auto sm:bottom-auto sm:left-0 sm:mt-2 sm:w-64 sm:rounded-xl sm:shadow-lg"
        >
          <button
            type="button"
            role="option"
            aria-selected={!any}
            onClick={() => {
              onChange([]);
              setOpen(false);
            }}
            className={`flex w-full items-center justify-between border-b border-slate-100 px-4 py-2.5 text-left text-sm transition hover:bg-slate-50 ${
              any ? "text-slate-700" : "font-medium text-slate-900"
            }`}
          >
            All owners
            {any ? (
              <span className="text-xs font-medium text-slate-400">Clear {selected.length}</span>
            ) : (
              <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-slate-900" fill="currentColor" aria-hidden>
                <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0l-3.5-3.5a1 1 0 011.4-1.4l2.8 2.79 6.8-6.79a1 1 0 011.4 0z" clipRule="evenodd" />
              </svg>
            )}
          </button>
          <ul className="max-h-[55vh] overflow-y-auto p-1 sm:max-h-72">
            {owners.map((owner) => {
              const on = selected.includes(owner);
              return (
                <li key={owner}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={on}
                    onClick={() => toggle(owner)}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition ${
                      on ? "bg-slate-100 font-semibold text-slate-900" : "text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    {/* Checkbox look: several owners can be chosen. */}
                    <span
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                        on ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white"
                      }`}
                      aria-hidden
                    >
                      {on && (
                        <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor">
                          <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0l-3.5-3.5a1 1 0 011.4-1.4l2.8 2.79 6.8-6.79a1 1 0 011.4 0z" clipRule="evenodd" />
                        </svg>
                      )}
                    </span>
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${avatarColor(owner)}`}>
                      {initials(owner)}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{owner}</span>
                    <span className="shrink-0 text-xs font-normal tabular-nums text-slate-400">
                      {counts[owner] ?? 0} task{counts[owner] === 1 ? "" : "s"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
