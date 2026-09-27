"use client";

import OwnerFilter from "@/components/OwnerFilter";

interface Props {
  owners: string[];
  /** Tasks per owner among the tasks on screen, for the owner dropdown. */
  ownerCounts: Record<string, number>;
  /** The owners chosen in the owner filter; empty for everyone. */
  selectedOwners: string[];
  onOwnersChange: (owners: string[]) => void;
  sortByDeadline: boolean;
  onSortToggle: () => void;
  /** The "Sort by deadline" toggle is meaningless in the calendar view, so it can be hidden. */
  showSort?: boolean;
  /** A further filter shown after the owner filter (the Meeting filter). */
  extra?: React.ReactNode;
}

export default function Filters({
  owners,
  ownerCounts,
  selectedOwners,
  onOwnersChange,
  sortByDeadline,
  onSortToggle,
  showSort = true,
  extra,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-display text-sm font-semibold text-slate-500">Filter</span>

      {owners.length > 0 && (
        <OwnerFilter owners={owners} counts={ownerCounts} selected={selectedOwners} onChange={onOwnersChange} />
      )}
      {extra}

      <div className="ml-auto flex items-center gap-2">
      {showSort && (
        <button
          onClick={onSortToggle}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
            sortByDeadline
              ? "bg-slate-900 text-white"
              : "text-slate-600 hover:bg-slate-900/5"
          }`}
        >
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
            <path d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm2 5a1 1 0 011-1h8a1 1 0 110 2H6a1 1 0 01-1-1zm3 4a1 1 0 100 2h4a1 1 0 100-2H8z" />
          </svg>
          Sort by deadline
        </button>
      )}
      </div>
    </div>
  );
}
