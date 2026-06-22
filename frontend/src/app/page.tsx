"use client";

import { useEffect } from "react";

import LandingContent from "@/components/LandingContent";

// The root always shows the landing page — visitors read the intro, then click
// through to the app where they pick "log in" or "continue as guest" (and a
// returning session simply resumes where they left off).
//
// The one exception is a share link (/?w=token): that recipient came to open a
// specific board, so we forward them straight to the app with the token intact,
// preserving the existing share-link contract. The site is statically exported
// (no server), so this check runs in the browser on mount rather than server-side.
export default function Home() {
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("w");
    if (token) {
      window.location.replace(`/app?w=${encodeURIComponent(token)}`);
    }
  }, []);

  return <LandingContent />;
}
