import type { Metadata } from "next";

import LandingContent from "@/components/LandingContent";

export const metadata: Metadata = {
  title: "Meeting Orchestrator: turn meeting transcripts into tracked action items",
  description:
    "AI-powered meeting and workflow orchestrator. Drop in a raw transcript or recording and get decisions, owners, and deadlines on a live Kanban board, with no manual minute-taking.",
};

export default function LandingPage() {
  return <LandingContent />;
}
