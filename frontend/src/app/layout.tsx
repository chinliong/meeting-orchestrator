import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meeting Orchestrator — AI action items from transcripts",
  description:
    "AI-powered meeting transcript parsing that extracts decisions, action items, owners, and deadlines onto a Kanban board.",
  icons: { icon: "/logo.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
