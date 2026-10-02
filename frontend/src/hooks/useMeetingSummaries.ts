"use client";

import { useCallback, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { MeetingListItem, MeetingSummary } from "@/lib/types";

const SUMMARY_FAILED = "Couldn't write a summary right now. Please try again.";
/** How long to wait for the summary the server writes after a meeting is added. */
const WAIT_MS = 60 * 1000;
const POLL_MS = 2000;

/**
 * Meeting summaries written in this session (newer than the loaded meeting list), and the ones
 * being written or that failed, each by meeting id.
 *
 * `editable` is whether the viewer can write summaries: a view-only reader cannot try again, so
 * they are not shown a failure, just that there is no summary.
 */
export function useMeetingSummaries(editable: boolean) {
  const [fresh, setFresh] = useState<Record<number, MeetingSummary>>({});
  const [working, setWorking] = useState<Record<number, true>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});

  const start = (meetingId: number) => {
    setWorking((cur) => ({ ...cur, [meetingId]: true }));
    setErrors(({ [meetingId]: _cleared, ...rest }) => rest);
  };
  const finish = (meetingId: number) => setWorking(({ [meetingId]: _done, ...rest }) => rest);

  // After a meeting is added, the server writes its summary on its own (so it is written even if
  // the page is closed). Wait for it here, up to a minute, rather than asking for a second one.
  const waitForSummary = useCallback(async (meetingId: number, boardToken?: string) => {
    start(meetingId);
    const deadline = Date.now() + WAIT_MS;
    try {
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        try {
          const current = await api.getMeeting(meetingId, boardToken);
          const written = current.summary;
          if (written) {
            setFresh((cur) => ({ ...cur, [meetingId]: written }));
            return;
          }
          if (current.summary_failed) break; // the server tried and could not: say so now
        } catch (err) {
          if (err instanceof ApiError) return; // e.g. the meeting was deleted meanwhile
        }
      }
      setErrors((cur) => ({ ...cur, [meetingId]: SUMMARY_FAILED }));
    } finally {
      finish(meetingId);
    }
  }, []);

  // Writes (or rewrites) a meeting's summary on request, from the summary card's button.
  // `boardToken` pins the meeting's board.
  const requestSummary = useCallback(async (meetingId: number, boardToken?: string) => {
    start(meetingId);
    try {
      const summary = await api.summariseMeeting(meetingId, boardToken);
      setFresh((cur) => ({ ...cur, [meetingId]: summary }));
    } catch (err) {
      const message = err instanceof ApiError && err.status === 429 ? err.message : SUMMARY_FAILED;
      setErrors((cur) => ({ ...cur, [meetingId]: message }));
    } finally {
      finish(meetingId);
    }
  }, []);

  /** The meeting's summary: one written in this session, else the one it was loaded with. */
  const summaryFor = (m: MeetingListItem) => fresh[m.id] ?? m.summary;
  const isWorking = (m: MeetingListItem) => !!working[m.id];
  // A summary the server could not write (it records the failure) shows the same message and
  // Try again as a failed request, also after a reload, unless one has been written since.
  const errorFor = (m: MeetingListItem) =>
    errors[m.id] ?? (editable && m.summary_failed && !fresh[m.id] && !working[m.id] ? SUMMARY_FAILED : null);

  return { waitForSummary, requestSummary, summaryFor, isWorking, errorFor };
}
