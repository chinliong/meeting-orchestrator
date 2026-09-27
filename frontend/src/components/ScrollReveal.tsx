"use client";

import { useEffect } from "react";

/**
 * The landing page's scroll animation. Elements marked `data-reveal` fade into place whenever they
 * scroll into view, in either direction: rising from below when scrolling down, dropping in from
 * above when scrolling back up. Once fully off screen they are reset, ready to animate again.
 * Numbers marked `data-count` (e.g. "96%") count up from zero, the first time only.
 *
 * Content is never hidden unless this can show it again: the hiding class (`reveal-ready` on
 * <html>) is set only where motion is allowed and IntersectionObserver exists, the inline script
 * in LandingContent removes it again if this component has not started within three seconds (e.g.
 * the page's JavaScript failed to load), and "Reduce motion" skips all of it.
 */
export default function ScrollReveal() {
  useEffect(() => {
    const root = document.documentElement;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) {
      root.classList.remove("reveal-ready");
      return;
    }
    root.classList.add("reveal-ready", "reveal-live");

    const counters = Array.from(document.querySelectorAll<HTMLElement>("[data-count]"));
    counters.forEach((el) => (el.textContent = `0${el.dataset.suffix ?? ""}`));

    const countUp = (el: HTMLElement) => {
      const target = Number(el.dataset.count);
      const suffix = el.dataset.suffix ?? "";
      const start = performance.now();
      const duration = 1100;
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        el.textContent = `${Math.round(target * eased)}${suffix}`;
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const el = entry.target as HTMLElement;
          if (entry.intersectionRatio >= 0.15) {
            el.classList.add("is-visible");
            el.querySelectorAll<HTMLElement>("[data-count]:not([data-counted])").forEach((n) => {
              n.dataset.counted = "";
              countUp(n);
            });
          } else if (!entry.isIntersecting) {
            // Fully off screen: reset it, remembering which side it left by, so that it comes back in
            // from that side.
            el.classList.remove("is-visible");
            el.classList.toggle("from-above", entry.boundingClientRect.top < 0);
          }
        }
      },
      { threshold: [0, 0.15] }
    );
    document.querySelectorAll("[data-reveal]").forEach((el) => observer.observe(el));

    return () => {
      observer.disconnect();
      root.classList.remove("reveal-ready", "reveal-live");
      // Leave the numbers correct if the page is left mid-count.
      counters.forEach((el) => (el.textContent = `${el.dataset.count}${el.dataset.suffix ?? ""}`));
    };
  }, []);

  return null;
}
