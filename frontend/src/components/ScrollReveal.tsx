"use client";

import { useEffect } from "react";

// Watches every [data-reveal] element on the page and adds .is-visible once it
// scrolls into view, driving the CSS transition in globals.css. Renders nothing.
export default function ScrollReveal() {
  useEffect(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    if (els.length === 0) return;

    // No IntersectionObserver (or reduced motion) → just show everything.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      els.forEach((el) => el.classList.add("is-visible"));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          // Toggle, don't latch: re-arm every element as it leaves and re-enters
          // the viewport so the reveal replays consistently on each scroll past.
          entry.target.classList.toggle("is-visible", entry.isIntersecting);
        }
      },
      { threshold: 0.18, rootMargin: "0px 0px -12% 0px" },
    );

    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return null;
}
