"use client";

import { avatarColor, initials } from "@/lib/format";

interface Props {
  owners: string[];
  selectedOwner: string;
  onOwnerChange: (owner: string) => void;
  sortByDeadline: boolean;
  onSortToggle: () => void;
}

export default function Filters({
  owners,
  selectedOwner,
  onOwnerChange,
  sortByDeadline,
  onSortToggle,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium text-slate-500">Filter</span>

      {/* "All" pill */}
      <button
        onClick={() => onOwnerChange("")}
        className={`rounded-full px-3 py-1 text-sm font-medium transition ${
          selectedOwner === ""
            ? "bg-slate-900 text-white"
            : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
        }`}
      >
        All owners
      </button>

      {owners.map((owner) => {
        const active = selectedOwner === owner;
        return (
          <button
            key={owner}
            onClick={() => onOwnerChange(active ? "" : owner)}
            className={`inline-flex items-center gap-1.5 rounded-full py-1 pl-1 pr-3 text-sm font-medium transition ${
              active
                ? "bg-indigo-600 text-white"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold text-white ${avatarColor(
                owner
              )}`}
            >
              {initials(owner)}
            </span>
            {owner}
          </button>
        );
      })}

      <button
        onClick={onSortToggle}
        className={`ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
          sortByDeadline
            ? "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200"
            : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
        }`}
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
          <path d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm2 5a1 1 0 011-1h8a1 1 0 110 2H6a1 1 0 01-1-1zm3 4a1 1 0 100 2h4a1 1 0 100-2H8z" />
        </svg>
        Sort by deadline
      </button>
    </div>
  );
}
