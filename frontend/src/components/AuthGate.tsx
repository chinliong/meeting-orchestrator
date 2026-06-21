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
type View = "auth" | "reset";
type ResetStage = "request" | "confirm";

// Pull the server's human-readable detail out of the api.ts error wrapper.
function readableError(err: unknown): string {
  const raw = err instanceof Error ? err.message : "Something went wrong";
  const match = raw.match(/"detail":"([^"]+)"/);
  return match ? match[1] : raw;
}

export default function AuthGate({ claimTokens, onAuthed, onGuest, allowGuest = true, onCancel }: Props) {
  const [view, setView] = useState<View>("auth");
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- reset-password flow state ---
  const [resetStage, setResetStage] = useState<ResetStage>("request");
  const [resetEmail, setResetEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  // A success banner shown on the login form after a completed reset.
  const [loginNotice, setLoginNotice] = useState<string | null>(null);

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
      setError(readableError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const goToReset = () => {
    setView("reset");
    setResetStage("request");
    setResetEmail(email.trim());
    setCode("");
    setNewPassword("");
    setError(null);
    setResetNotice(null);
  };

  const backToLogin = (notice?: string) => {
    setView("auth");
    setMode("login");
    setError(null);
    setResetNotice(null);
    setLoginNotice(notice ?? null);
  };

  const handleRequestCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetEmail.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.forgotPassword(resetEmail.trim());
      setResetStage("confirm");
      setResetNotice("If an account exists for that email, a 6-digit code is on its way. Enter it below.");
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirmReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim() || !newPassword) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.resetPassword(resetEmail.trim(), code.trim(), newPassword);
      backToLogin("Password reset. Sign in with your new password.");
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const shell = (children: React.ReactNode) => (
    <div className="mx-auto mt-16 max-w-sm rounded-2xl border border-slate-200 bg-white p-7 shadow-card">
      <div className="mb-5 flex flex-col items-center text-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.png" alt="Meeting Orchestrator logo" className="mb-3 h-14 w-14 rounded-full object-cover" />
        <h1 className="font-display text-lg font-bold tracking-tight text-slate-900">Meeting Orchestrator</h1>
      </div>
      {children}
    </div>
  );

  // --- forgot/reset password view ---
  if (view === "reset") {
    return shell(
      <>
        <p className="mb-4 text-center text-sm text-slate-500">
          {resetStage === "request"
            ? "Enter your email and we'll send a 6-digit reset code."
            : "Enter the code from your email and choose a new password."}
        </p>

        {resetStage === "request" ? (
          <form onSubmit={handleRequestCode} className="space-y-3">
            <input
              type="email"
              autoFocus
              value={resetEmail}
              onChange={(e) => setResetEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
            {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={submitting || !resetEmail.trim()}
              className="w-full rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700 disabled:opacity-50"
            >
              {submitting ? "Sending..." : "Send code"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleConfirmReset} className="space-y-3">
            {resetNotice && (
              <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{resetNotice}</p>
            )}
            <input
              type="text"
              inputMode="numeric"
              autoFocus
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              placeholder="6-digit code"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-center text-lg tracking-[0.4em] outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
            <input
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
            {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={submitting || code.length < 6 || !newPassword}
              className="w-full rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700 disabled:opacity-50"
            >
              {submitting ? "Resetting..." : "Reset password"}
            </button>
          </form>
        )}

        <button
          onClick={() => backToLogin()}
          className="mt-4 w-full text-center text-xs font-medium text-slate-500 hover:text-slate-700"
        >
          Back to sign in
        </button>
      </>
    );
  }

  // --- login / signup view ---
  return shell(
    <>
      <p className="-mt-3 mb-4 text-center text-sm text-slate-500">
        {mode === "signup" ? "Create an account to save your boards." : "Sign in to your boards."}
      </p>

      <div className="mb-4 flex rounded-lg bg-slate-100 p-1">
        {tab("login", "Sign in")}
        {tab("signup", "Create account")}
      </div>

      {loginNotice && mode === "login" && (
        <p className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{loginNotice}</p>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="email"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
        />

        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting || !email.trim() || !password}
          className="w-full rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-ink-700 disabled:opacity-50"
        >
          {submitting ? "Please wait..." : mode === "signup" ? "Create account" : "Sign in"}
        </button>
      </form>

      {mode === "login" && (
        <button
          onClick={goToReset}
          className="mt-3 w-full text-center text-xs font-medium text-slate-500 hover:text-slate-700"
        >
          Forgot password?
        </button>
      )}

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
    </>
  );
}
