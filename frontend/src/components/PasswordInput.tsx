"use client";

import { useState } from "react";

type Props = Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">;

/**
 * Password field with a show/hide eye toggle. Spreads through every native input prop
 * (value, onChange, placeholder, autoComplete, ...) so it drops in wherever a plain
 * `<input type="password" />` was used. Adds right padding to make room for the button.
 */
export default function PasswordInput({ className = "", ...props }: Props) {
  const [visible, setVisible] = useState(false);
  const base =
    "w-full rounded-lg border border-slate-300 px-3 py-2 pr-10 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

  return (
    <div className="relative">
      <input type={visible ? "text" : "password"} className={`${base} ${className}`.trim()} {...props} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
        aria-label={visible ? "Hide password" : "Show password"}
        title={visible ? "Hide password" : "Show password"}
        className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 transition hover:text-slate-600"
      >
        {visible ? (
          // eye-off
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
            <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
            <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
            <line x1="2" y1="2" x2="22" y2="22" />
          </svg>
        ) : (
          // eye
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}
