"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { UndoAction } from "@/lib/types";

/** The most actions the history keeps; the oldest is dropped beyond this. */
const MAX_UNDO = 50;

/**
 * The board's undo history: a stack whose entries each perform the inverse of an action.
 *
 * Undo runs with the current board's credentials and updates the tasks on screen, so the history
 * is cleared whenever `resetKey` changes (switching board or view, signing in or out). Cmd/Ctrl+Z
 * anywhere on the page undoes, except while typing in a field.
 */
export function useUndoHistory(resetKey: string, onError: (message: string) => void) {
  const stackRef = useRef<UndoAction[]>([]);
  const [depth, setDepth] = useState(0);
  // Bumped on every undo so an open card re-seeds its fields from the reverted task.
  const [nonce, setNonce] = useState(0);
  // Bumped whenever the history is cleared. A handler notes it (generation()) before its request,
  // so an action that finishes after the user has switched boards is not added to the new board's
  // history.
  const genRef = useRef(0);

  const clear = useCallback(() => {
    genRef.current += 1;
    stackRef.current = [];
    setDepth(0);
  }, []);

  useEffect(clear, [resetKey, clear]);

  const generation = useCallback(() => genRef.current, []);

  /** Add an action's inverse; `gen` drops it if the history was cleared since the action began. */
  const push = useCallback((action: UndoAction, gen?: number) => {
    if (gen !== undefined && gen !== genRef.current) return;
    stackRef.current.push(action);
    if (stackRef.current.length > MAX_UNDO) stackRef.current.shift();
    setDepth(stackRef.current.length);
  }, []);

  const undo = useCallback(async () => {
    const action = stackRef.current.pop();
    setDepth(stackRef.current.length);
    if (!action) return;
    try {
      await action.run();
      setNonce((n) => n + 1);
    } catch (err) {
      onError((err as Error).message);
    }
  }, [onError]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.key.toLowerCase() !== "z") return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      e.preventDefault();
      undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo]);

  return { depth, nonce, push, undo, clear, generation };
}
