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

// Soft per-person tints: a pale fill with the initials in a deep shade of the same hue. Kept pale
// so they never compete with the saturated status colours on the board, and written out in full so
// Tailwind keeps every class.
const AVATAR_COLORS = [
  "bg-indigo-100 text-indigo-700",
  "bg-violet-100 text-violet-700",
  "bg-fuchsia-100 text-fuchsia-700",
  "bg-pink-100 text-pink-700",
  "bg-sky-100 text-sky-700",
  "bg-teal-100 text-teal-700",
  "bg-orange-100 text-orange-700",
  "bg-stone-200 text-stone-700",
];

/**
 * The avatar colour for a name; the same name always gets the same colour. FNV-1a with a final
 * mix, so names spread evenly over the palette (a plain `hash * 31` leaves the low bits, which pick
 * the colour, poorly mixed, and many names collide).
 */
export function avatarColor(name: string): string {
  let x = 0x811c9dc5;
  for (let i = 0; i < name.length; i++) {
    x ^= name.charCodeAt(i);
    x = Math.imul(x, 0x01000193);
  }
  x ^= x >>> 15;
  x = Math.imul(x, 0x2c1b3c6d);
  x ^= x >>> 12;
  return AVATAR_COLORS[(x >>> 0) % AVATAR_COLORS.length];
}

/** Format an ISO date (YYYY-MM-DD) as e.g. "Jun 19". */
export function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Meeting date as "Aug 04, 2026", the same format the backend uses in untitled meeting names.
 * With `short`, the year is dropped when it is the current year ("Aug 04").
 */
export function formatMeetingDate(iso: string, short = false): string {
  const d = new Date(`${iso}T00:00:00`);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    ...(short && sameYear ? {} : { year: "numeric" }),
  });
}

/**
 * When a meeting was added, in the viewer's time, e.g. "Sep 25, 2:41 PM", or with `seconds`
 * "Sep 25, 2:41:05 PM" (to tell apart two meetings added in the same minute). The API sends UTC
 * timestamps without a zone suffix, so one is added before parsing.
 */
export function formatAddedAt(iso: string, seconds = false): string {
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
  });
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
  if (confidence >= LOW_CONFIDENCE) return "text-emerald-600";
  if (confidence >= 0.6) return "text-amber-600";
  return "text-slate-400";
}

/**
 * Below this, a card is flagged for review rather than shown as a percentage.
 *
 * Set from Claude Sonnet's scores: every Sonnet item scored below 0.85 in the evaluation was
 * spurious. Gemini Flash, the implemented model, never scored an item below 0.85, so on it the
 * flag rarely if ever fires. The score is not a calibrated probability on either model.
 * See docs/evaluation-appendix.md, "Is the confidence score meaningful?".
 */
export const LOW_CONFIDENCE = 0.85;

export function isLowConfidence(confidence: number): boolean {
  return confidence < LOW_CONFIDENCE;
}
