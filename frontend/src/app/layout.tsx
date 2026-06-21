import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";

// Inter carries the reading body; Space Grotesk is the geometric display voice
// (headings, stat numbers, labels) that gives the board its considered, professional feel.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Meeting Orchestrator — AI action items from transcripts",
  description:
    "AI-powered meeting transcript parsing that extracts decisions, action items, owners, and deadlines onto a Kanban board.",
  icons: { icon: "/logo.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${spaceGrotesk.variable}`}>
      <body className="min-h-screen text-slate-900 antialiased">{children}</body>
    </html>
  );
}
