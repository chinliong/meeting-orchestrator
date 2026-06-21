// Small presentation helpers shared across the dashboard UI.

export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

// Distinct per-person colours with warm/cool variety so owners are easy to tell apart.
// Deliberately avoids brand blue (the To Do status) and emerald (Done) so an avatar is
// never confused with a status colour.
const AVATAR_COLORS = [
  "bg-indigo-500",
  "bg-rose-500",
  "bg-amber-500",
  "bg-violet-500",
  "bg-orange-500",
  "bg-teal-500",
  "bg-fuchsia-500",
  "bg-cyan-600",
  "bg-pink-500",
];

export function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

/** Format an ISO date (YYYY-MM-DD) as e.g. "Jun 19". */
export function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** True if the deadline is strictly before today (local time). */
export function isOverdue(iso: string): boolean {
  const d = new Date(`${iso}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return d < today;
}

/** Human-readable file size, e.g. 2048 → "2 KB", 1500000 → "1.4 MB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}

/**
 * Accent colour for the confidence meter, by how explicit the extraction was.
 * The chip itself stays a neutral chip; this colours just the icon + number so
 * high/medium/low still reads at a glance without a loud coloured pill.
 */
export function confidenceColor(confidence: number): string {
  if (confidence >= 0.85) return "text-emerald-600";
  if (confidence >= 0.6) return "text-amber-600";
  return "text-slate-400";
}
