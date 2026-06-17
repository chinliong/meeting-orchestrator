import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meeting & Workflow Orchestrator",
  description: "AI-powered meeting transcript parsing and task tracking",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
