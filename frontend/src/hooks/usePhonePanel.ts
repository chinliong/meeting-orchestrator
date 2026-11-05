"use client";

import { useEffect, useState, type CSSProperties, type RefObject } from "react";

/** Below Tailwind's `sm` breakpoint. */
const PHONE_MAX = 640;
/** The page's side margin on a phone (px-4). */
const GUTTER = 16;

/**
 * Placement for a dropdown that opens directly below its button on a phone, spanning the screen.
 *
 * The panel is positioned against the button's wrapper (`relative`). A button that sits towards the
 * right, such as "All meetings", would push a panel of any useful width off the screen, so on a
 * phone the panel is shifted to line up with the page margins instead. From `sm` up this returns
 * nothing and the panel's own classes place it.
 *
 * It is worked out while rendering, before the panel is on the page: measured afterwards, a panel
 * first drawn at its natural width would already have widened a phone's page.
 */
export function usePhonePanel(open: boolean, anchor: RefObject<HTMLElement>): CSSProperties | undefined {
  const [, setResized] = useState(0);
  useEffect(() => {
    if (!open) return;
    const onResize = () => setResized((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open]);
  if (!open || typeof window === "undefined") return undefined;
  const box = anchor.current?.getBoundingClientRect();
  const width = document.documentElement.clientWidth;
  if (!box || width >= PHONE_MAX) return undefined;
  return { left: GUTTER - box.left, width: width - GUTTER * 2 };
}
