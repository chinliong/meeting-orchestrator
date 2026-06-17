"use client";

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
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <label className="text-sm text-gray-600">
        Owner:{" "}
        <select
          value={selectedOwner}
          onChange={(e) => onOwnerChange(e.target.value)}
          className="ml-1 rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">All</option>
          {owners.map((owner) => (
            <option key={owner} value={owner}>
              {owner}
            </option>
          ))}
        </select>
      </label>
      <button
        onClick={onSortToggle}
        className={`rounded border px-3 py-1 text-sm ${
          sortByDeadline ? "border-blue-500 text-blue-600" : "border-gray-300 text-gray-600"
        }`}
      >
        Sort by deadline {sortByDeadline ? "✓" : ""}
      </button>
    </div>
  );
}
