import { redirect } from "next/navigation";

import LandingContent from "@/components/LandingContent";

// The root always shows the landing page — visitors read the intro, then click
// through to the app where they pick "log in" or "continue as guest" (and a
// returning session simply resumes where they left off).
//
// The one exception is a share link (/?w=token): that recipient came to open a
// specific board, so we forward them straight to the app with the token intact,
// preserving the existing share-link contract.
export default function Home({ searchParams }: { searchParams: { w?: string } }) {
  if (searchParams.w) {
    redirect(`/app?w=${encodeURIComponent(searchParams.w)}`);
  }
  return <LandingContent />;
}
