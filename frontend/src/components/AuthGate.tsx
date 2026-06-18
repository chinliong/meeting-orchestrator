"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import type { AuthResponse } from "@/lib/types";

interface Props {
  /** Edit tokens of guest boards to carry into a new account on sign-up. */
  claimTokens: string[];
  onAuthed: (auth: AuthResponse) => void;
  onGuest: () => void;
  /** Hide "continue as guest" when upgrading an existing guest session. */
  allowGuest?: boolean;
  onCancel?: () => void;
}

type Mode = "login" | "signup";

export default function AuthGate({ claimTokens, onAuthed, onGuest, allowGuest = true, onCancel }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tab = (m: Mode, label: string) => (
    <button
      type="button"
      onClick={() => {
        setMode(m);
        setError(null);
      }}
      className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition ${
        mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
      }`}
    >
      {label}
    </button>
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      const auth =
        mode === "signup"
          ? await api.signup(email.trim(), password, claimTokens)
          : await api.login(email.trim(), password);
      onAuthed(auth);
    } catch (err) {
      const raw = err instanceof Error ? err.message : "Something went wrong";
      // Surface the server's human message rather than the raw "POST ... failed" wrapper.
      const match = raw.match(/"detail":"([^"]+)"/);
      setError(match ? match[1] : raw);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-16 max-w-sm rounded-2xl border border-slate-200 bg-white p-7 shadow-card">
      <div className="mb-5 flex flex-col items-center text-center">
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm">
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor">
            <path d="M12 2l1.9 5.1L19 9l-5.1 1.9L12 16l-1.9-5.1L5 9l5.1-1.9L12 2z" />
          </svg>
        </div>
        <h1 className="text-lg font-semibold text-slate-900">Meeting Orchestrator</h1>
        <p className="mt-1 text-sm text-slate-500">
          {mode === "signup" ? "Create an account to save your boards." : "Sign in to your boards."}
        </p>
      </div>

      <div className="mb-4 flex rounded-lg bg-slate-100 p-1">
        {tab("login", "Sign in")}
        {tab("signup", "Create account")}
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="email"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
        />

        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting || !email.trim() || !password}
          className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-50"
        >
          {submitting ? "Please wait..." : mode === "signup" ? "Create account" : "Sign in"}
        </button>
      </form>

      {allowGuest && (
        <>
          <div className="my-4 flex items-center gap-3 text-xs text-slate-400">
            <span className="h-px flex-1 bg-slate-200" />
            or
            <span className="h-px flex-1 bg-slate-200" />
          </div>
          <button
            onClick={onGuest}
            className="w-full rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Continue as guest
          </button>
          <p className="mt-2 text-center text-xs text-slate-400">
            Guest boards live on this device and are reachable by share link.
          </p>
        </>
      )}

      {onCancel && (
        <button
          onClick={onCancel}
          className="mt-4 w-full text-center text-xs font-medium text-slate-500 hover:text-slate-700"
        >
          Back
        </button>
      )}
    </div>
  );
}
