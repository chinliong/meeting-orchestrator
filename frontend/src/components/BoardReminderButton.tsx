"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  /** The board has an owner account (a guest board cannot be subscribed to). */
  owned: boolean;
  /** The viewer is signed in. */
  signedIn: boolean;
  /** Whether the viewer gets this board's reminders; null while loading. */
  subscribed: boolean | null;
  busy: boolean;
  /** The viewer's email, named when their reminders are turned on. */
  email: string | null;
  onToggle: () => Promise<boolean>;
  onSignIn: () => void;
}

/**
 * "Remind me" on a board shared with the viewer: asks for the same deadline reminders the
 * board's owner gets. Guests are asked to sign in first (reminders go to a confirmed account),
 * and guest boards explain that reminders need a board saved to an account.
 */
export default function BoardReminderButton({ owned, signedIn, subscribed, busy, email, onToggle, onSignIn }: Props) {
  const [note, setNote] = useState<React.ReactNode>(null);
  const ref = useRef<HTMLDivElement>(null);

  // The note closes on an outside click or Escape.
  useEffect(() => {
    if (!note) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setNote(null);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNote(null);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [note]);

  const on = !!subscribed && owned && signedIn;

  const click = async () => {
    if (!owned) {
      setNote("Reminders are available on boards saved to an account.");
      return;
    }
    if (!signedIn) {
      setNote(
        <>
          <p>Sign in to get this board&apos;s deadline reminders by email.</p>
          <button
            type="button"
            onClick={() => {
              setNote(null);
              onSignIn();
            }}
            className="mt-2 rounded-lg bg-ink px-3 py-1.5 text-xs font-medium text-white transition hover:bg-ink-700"
          >
            Sign in
          </button>
        </>
      );
      return;
    }
    setNote(null);
    const nowOn = await onToggle();
    if (nowOn) {
      setNote(
        <p>
          You&apos;ll get an email{email ? <> at <span className="font-medium text-slate-900">{email}</span></> : null} when
          this board&apos;s tasks are about to be due. Change when in Account settings.
        </p>
      );
    }
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={click}
        disabled={busy || (signedIn && owned && subscribed === null)}
        aria-pressed={on}
        title={on ? "You get this board's deadline reminders. Click to stop them." : "Get this board's deadline reminders by email"}
        className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition disabled:opacity-50 ${
          on ? "text-brand-700 hover:bg-brand-50" : "text-slate-600 hover:bg-slate-900/5 hover:text-slate-900"
        }`}
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
          {on ? (
            <path d="M10 2a6 6 0 00-6 6v2.59l-.7.7A1 1 0 004 13h12a1 1 0 00.7-1.71l-.7-.7V8a6 6 0 00-6-6zm0 16a2.5 2.5 0 01-2.45-2h4.9A2.5 2.5 0 0110 18z" />
          ) : (
            <path
              fillRule="evenodd"
              d="M10 2a6 6 0 00-6 6v2.59l-.7.7A1 1 0 004 13h12a1 1 0 00.7-1.71l-.7-.7V8a6 6 0 00-6-6zM5.5 11.5V8a4.5 4.5 0 019 0v3.5H5.5zM10 18a2.5 2.5 0 01-2.45-2h4.9A2.5 2.5 0 0110 18z"
              clipRule="evenodd"
            />
          )}
        </svg>
        {on ? "Reminders on" : "Remind me"}
      </button>
      {note && (
        <div
          role="status"
          className="absolute left-0 z-30 mt-1.5 w-64 rounded-xl border border-slate-200 bg-white p-3 text-[13px] leading-snug text-slate-600 shadow-lg sm:left-auto sm:right-0"
        >
          {note}
        </div>
      )}
    </div>
  );
}
