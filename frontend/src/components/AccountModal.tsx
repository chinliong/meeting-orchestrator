"use client";

import { useEffect, useState } from "react";

import type { User } from "@/lib/types";

interface Props {
  open: boolean;
  user: User;
  onClose: () => void;
  onChangePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  onDeleteAccount: () => Promise<void>;
  onUpdateNotifications: (notifyEmail: boolean, notifyDaysBefore: number) => Promise<void>;
  onSendTestNotification: () => Promise<number>;
}

// Pull the server's human-readable detail out of the api.ts error wrapper.
function readableError(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message : fallback;
  const match = raw.match(/"detail":"([^"]+)"/);
  return match ? match[1] : raw;
}

export default function AccountModal({
  open,
  user,
  onClose,
  onChangePassword,
  onDeleteAccount,
  onUpdateNotifications,
  onSendTestNotification,
}: Props) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // --- notification settings ---
  const [notifyEmail, setNotifyEmail] = useState(user.notify_email);
  const [notifyDaysBefore, setNotifyDaysBefore] = useState(user.notify_days_before);
  const [notifySaving, setNotifySaving] = useState(false);
  const [notifyError, setNotifyError] = useState<string | null>(null);
  const [testSending, setTestSending] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  // Reset the form each time the modal opens, and close on Escape.
  useEffect(() => {
    if (open) {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setError(null);
      setSuccess(false);
      setConfirmingDelete(false);
      setDeleteError(null);
      setNotifyEmail(user.notify_email);
      setNotifyDaysBefore(user.notify_days_before);
      setNotifyError(null);
      setTestResult(null);
    }
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentPassword || !newPassword) return;
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match");
      return;
    }
    setSubmitting(true);
    setError(null);
    setSuccess(false);
    try {
      await onChangePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(readableError(err, "Failed to change password"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDeleteAccount();
      // Parent handles sign-out / navigation; no need to close here.
    } catch (err) {
      setDeleteError(readableError(err, "Failed to delete account"));
      setDeleting(false);
    }
  };

  // Persist a notification setting immediately on change, rather than behind a save button —
  // a toggle/select pair reads as "live settings," not a form that needs submitting.
  const saveNotifications = async (nextEmail: boolean, nextDays: number) => {
    setNotifySaving(true);
    setNotifyError(null);
    setTestResult(null);
    try {
      await onUpdateNotifications(nextEmail, nextDays);
    } catch (err) {
      setNotifyError(readableError(err, "Failed to update notification settings"));
      // Roll back the optimistic UI change.
      setNotifyEmail(user.notify_email);
      setNotifyDaysBefore(user.notify_days_before);
    } finally {
      setNotifySaving(false);
    }
  };

  const handleToggleNotify = () => {
    const next = !notifyEmail;
    setNotifyEmail(next);
    saveNotifications(next, notifyDaysBefore);
  };

  const handleDaysBeforeChange = (days: number) => {
    setNotifyDaysBefore(days);
    saveNotifications(notifyEmail, days);
  };

  const handleSendTest = async () => {
    setTestSending(true);
    setTestResult(null);
    setNotifyError(null);
    try {
      const count = await onSendTestNotification();
      setTestResult(
        count > 0
          ? `Sent — ${count} task${count === 1 ? "" : "s"} included.`
          : "Sent — you have no tasks due right now, so it's just a confirmation email."
      );
    } catch (err) {
      setNotifyError(readableError(err, "Failed to send test email"));
    } finally {
      setTestSending(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-md animate-fade-in rounded-2xl bg-white p-6 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-900">Account settings</h2>
        <p className="mt-1 text-sm text-slate-500">
          Signed in as <span className="font-medium text-slate-700">{user.email}</span>
        </p>

        {/* --- change password --- */}
        <form onSubmit={handleChangePassword} className="mt-5 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Change password</h3>
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            placeholder="Current password"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
          />
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="New password"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
          />
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Confirm new password"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
          />

          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
          {success && (
            <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              Password updated.
            </p>
          )}

          <button
            type="submit"
            disabled={submitting || !currentPassword || !newPassword}
            className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:opacity-50"
          >
            {submitting ? "Updating..." : "Update password"}
          </button>
        </form>

        {/* --- deadline email notifications --- */}
        <div className="mt-6 border-t border-slate-200 pt-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">Deadline reminders</h3>
              <p className="mt-0.5 text-xs text-slate-500">
                Get a digest email when a task is about to be due or has gone overdue.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={notifyEmail}
              onClick={handleToggleNotify}
              disabled={notifySaving}
              className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition disabled:opacity-50 ${
                notifyEmail ? "bg-slate-900" : "bg-slate-200"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition ${
                  notifyEmail ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>

          {notifyEmail && (
            <div className="mt-3 space-y-3">
              <label className="flex items-center gap-2 text-sm text-slate-700">
                Remind me
                <select
                  value={notifyDaysBefore}
                  onChange={(e) => handleDaysBeforeChange(Number(e.target.value))}
                  disabled={notifySaving}
                  className="rounded-lg border border-slate-300 px-2 py-1 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
                >
                  <option value={0}>on the due date</option>
                  <option value={1}>1 day before</option>
                  <option value={2}>2 days before</option>
                  <option value={3}>3 days before</option>
                  <option value={7}>1 week before</option>
                </select>
              </label>

              <div>
                <button
                  type="button"
                  onClick={handleSendTest}
                  disabled={testSending}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50 disabled:opacity-50"
                >
                  {testSending ? "Sending..." : "Send test email"}
                </button>
                {testResult && <p className="mt-2 text-xs text-emerald-700">{testResult}</p>}
              </div>
            </div>
          )}

          {notifyError && (
            <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{notifyError}</p>
          )}
        </div>

        {/* --- danger zone --- */}
        <div className="mt-6 border-t border-slate-200 pt-5">
          <h3 className="text-sm font-semibold text-rose-600">Delete account</h3>
          <p className="mt-1 text-sm text-slate-500">
            Your account is removed permanently. Your boards are kept and stay reachable by their
            existing share links.
          </p>

          {deleteError && (
            <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{deleteError}</p>
          )}

          {confirmingDelete ? (
            <div className="mt-3 flex gap-2">
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-rose-700 disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Yes, delete my account"}
              </button>
              <button
                onClick={() => setConfirmingDelete(false)}
                disabled={deleting}
                className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmingDelete(true)}
              className="mt-3 rounded-lg px-4 py-2 text-sm font-medium text-rose-600 ring-1 ring-rose-200 transition hover:bg-rose-50"
            >
              Delete account
            </button>
          )}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
