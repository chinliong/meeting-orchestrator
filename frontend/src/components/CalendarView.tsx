"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Task } from "@/lib/types";
import { avatarColor, initials, isOverdue } from "@/lib/format";

interface Props {
  tasks: Task[];
  /** False for view-only (shared) boards: drag-to-reschedule and delete are disabled. */
  canEdit: boolean;
  onEditTask: (task: Task) => void;
  onDeleteTask: (taskId: number) => void;
  /** Move a task's deadline to the given ISO date, or null to clear it. */
  onReschedule: (taskId: number, deadline: string | null) => void;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const STATUS_DOT: Record<Task["status"], string> = {
  todo: "bg-status-todo",
  in_progress: "bg-status-progress",
  done: "bg-status-done",
};

function toISO(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export default function CalendarView({ tasks, canEdit, onEditTask, onDeleteTask, onReschedule }: Props) {
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const [dragOver, setDragOver] = useState<string | null>(null); // ISO day, or "tray"
  // Dragging with a finger: the browser's drag and drop needs a mouse, so on a touch screen a task
  // is picked up by pressing and holding it, then follows the finger (see the effect below).
  const [touchDrag, setTouchDrag] = useState<{ task: Task; x: number; y: number } | null>(null);
  const held = useRef<Task | null>(null);
  const reschedule = useRef(onReschedule);
  reschedule.current = onReschedule;
  const press = useRef<{ timer: number; x: number; y: number } | null>(null);
  const finger = useRef({ x: 0, y: 0 });
  const scroller = useRef<HTMLDivElement>(null);
  const [touchScreen, setTouchScreen] = useState(false);
  useEffect(() => setTouchScreen(window.matchMedia("(hover: none)").matches), []);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerYear, setPickerYear] = useState(() => new Date().getFullYear());

  const todayISO = toISO(new Date());

  const byDate = useMemo(() => {
    const map = new Map<string, Task[]>();
    for (const t of tasks) {
      if (!t.deadline) continue;
      const list = map.get(t.deadline) ?? [];
      list.push(t);
      map.set(t.deadline, list);
    }
    return map;
  }, [tasks]);

  const unscheduled = useMemo(() => tasks.filter((t) => !t.deadline), [tasks]);

  const cells = useMemo(() => {
    const first = startOfMonth(month);
    const offset = (first.getDay() + 6) % 7; // Mon = 0
    const start = new Date(first);
    start.setDate(first.getDate() - offset);
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      return d;
    });
  }, [month]);

  const openPicker = () => {
    setPickerYear(month.getFullYear());
    setPickerOpen(true);
  };

  const onDragStart = (e: React.DragEvent, task: Task) => {
    e.dataTransfer.setData("taskId", String(task.id));
  };

  // target: an ISO date string, or null to clear the deadline (the "no deadline" tray).
  const onDrop = (e: React.DragEvent, target: string | null) => {
    e.preventDefault();
    setDragOver(null);
    if (!canEdit) return;
    const id = Number(e.dataTransfer.getData("taskId"));
    if (id) onReschedule(id, target);
  };

  const cancelPress = () => {
    if (press.current) window.clearTimeout(press.current.timer);
    press.current = null;
  };

  // Pressing and holding a task for a moment picks it up; moving first is a scroll, not a drag.
  const onTouchStart = (e: React.TouchEvent, task: Task) => {
    if (!canEdit || e.touches.length !== 1) return;
    const { clientX: x, clientY: y } = e.touches[0];
    cancelPress();
    press.current = {
      x,
      y,
      timer: window.setTimeout(() => {
        press.current = null;
        finger.current = { x, y };
        held.current = task;
        setTouchDrag({ task, x, y });
        navigator.vibrate?.(15);
      }, 350),
    };
  };
  const onTouchMove = (e: React.TouchEvent) => {
    const t = e.touches[0];
    if (press.current && Math.hypot(t.clientX - press.current.x, t.clientY - press.current.y) > 8) cancelPress();
  };

  // While a task is held: it follows the finger, the day under it is highlighted, the page does not
  // scroll, and holding near an edge scrolls the calendar (sideways) or the page (up and down).
  const dragging = touchDrag !== null;
  useEffect(() => {
    if (!dragging) return;
    const target = (x: number, y: number) =>
      (document.elementFromPoint(x, y) as HTMLElement | null)?.closest<HTMLElement>("[data-day]")?.dataset.day ?? null;
    const onMove = (e: TouchEvent) => {
      e.preventDefault();
      const t = e.touches[0];
      finger.current = { x: t.clientX, y: t.clientY };
      setTouchDrag((cur) => (cur ? { ...cur, x: t.clientX, y: t.clientY } : cur));
      setDragOver(target(t.clientX, t.clientY));
    };
    const onEnd = (e: TouchEvent) => {
      e.preventDefault(); // no click afterwards, which would open the task
      const t = e.changedTouches[0];
      const day = target(t.clientX, t.clientY);
      const task = held.current;
      held.current = null;
      if (task && day) {
        const deadline = day === "tray" ? null : day;
        if (deadline !== task.deadline) reschedule.current(task.id, deadline);
      }
      setTouchDrag(null);
      setDragOver(null);
    };
    const onCancel = () => {
      held.current = null;
      setTouchDrag(null);
      setDragOver(null);
    };
    const edgeScroll = window.setInterval(() => {
      const { x, y } = finger.current;
      const box = scroller.current?.getBoundingClientRect();
      if (box && scroller.current && y >= box.top && y <= box.bottom) {
        if (x > window.innerWidth - 40) scroller.current.scrollLeft += 8;
        else if (x < 40) scroller.current.scrollLeft -= 8;
      }
      // Up when the finger reaches the sticky header, down near the bottom of the screen.
      const top = document.querySelector("header")?.getBoundingClientRect().bottom ?? 0;
      if (y > window.innerHeight - 60) window.scrollBy(0, 10);
      else if (y < top + 24) window.scrollBy(0, -10);
    }, 16);
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", onEnd, { passive: false });
    document.addEventListener("touchcancel", onCancel);
    return () => {
      window.clearInterval(edgeScroll);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
      document.removeEventListener("touchcancel", onCancel);
    };
  }, [dragging]);

  // Called as a function, not used as a component: a component declared in here would be a new
  // type on every render, so each chip would be replaced while a finger is dragging it.
  const chip = (task: Task, faded?: boolean) => {
    const overdue = task.deadline && task.status !== "done" && isOverdue(task.deadline);
    return (
      <div
        key={task.id}
        draggable={canEdit && !touchScreen}
        onDragStart={(e) => onDragStart(e, task)}
        onTouchStart={(e) => onTouchStart(e, task)}
        onTouchMove={onTouchMove}
        onTouchEnd={cancelPress}
        onContextMenu={(e) => canEdit && touchScreen && e.preventDefault()}
        className={`group/chip relative flex w-full select-none items-center gap-1 rounded px-1.5 py-1 text-[11px] font-medium transition [-webkit-touch-callout:none] ${touchDrag?.task.id === task.id ? "opacity-40" : ""} ${
          overdue ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-700"
        } ${canEdit ? "cursor-grab active:cursor-grabbing" : ""} ${faded ? "opacity-60" : ""}`}
      >
        <button
          onClick={() => onEditTask(task)}
          title={`${task.description}${task.owner ? ` — ${task.owner}` : ""}`}
          className="flex min-w-0 flex-1 items-center gap-1 text-left"
        >
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[task.status]}`} />
          <span className="truncate">{task.description}</span>
        </button>

        {(task.subtask_total > 0 || task.attachment_count > 0) && (
          <span
            className={`flex shrink-0 items-center gap-1 text-[9px] font-medium text-slate-500 ${
              canEdit ? "group-hover/chip:hidden [@media(hover:none)]:hidden" : ""
            }`}
          >
            {task.subtask_total > 0 && (
              <span className="inline-flex items-center gap-0.5" title={`${task.subtask_done}/${task.subtask_total} subtasks done`}>
                <svg viewBox="0 0 20 20" className="h-2.5 w-2.5" fill="currentColor">
                  <path d="M3 5.5A1.5 1.5 0 014.5 4h.7l1 1H4.5v9h11V8.8l1.5-1.5v7.2A1.5 1.5 0 0115.5 16h-11A1.5 1.5 0 013 14.5v-9zm14.7-1.2a1 1 0 010 1.4l-7 7a1 1 0 01-1.4 0L6 9.4a1 1 0 011.4-1.4l1.6 1.6 6.3-6.3a1 1 0 011.4 0z" />
                </svg>
                {task.subtask_done}/{task.subtask_total}
              </span>
            )}
            {task.attachment_count > 0 && (
              <span className="inline-flex items-center gap-0.5" title={`${task.attachment_count} attachment(s)`}>
                <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="2.4">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
                </svg>
                {task.attachment_count}
              </span>
            )}
          </span>
        )}

        {task.owner && (
          <span
            title={task.owner}
            className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[8px] font-semibold ${avatarColor(
              task.owner
            )} ${canEdit ? "group-hover/chip:hidden [@media(hover:none)]:hidden" : ""}`}
          >
            {initials(task.owner)}
          </span>
        )}

        {canEdit && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDeleteTask(task.id);
            }}
            aria-label="Delete task"
            className="hidden shrink-0 rounded p-0.5 text-slate-400 transition hover:text-rose-500 group-hover/chip:block [@media(hover:none)]:block"
          >
            <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {/* Header: clickable month/year picker + navigation */}
      <div className="flex items-center justify-between">
        <div className="relative">
          <button
            onClick={openPicker}
            className="inline-flex items-center gap-1.5 rounded-lg px-1 font-display text-lg font-bold tracking-tight text-slate-900 transition hover:text-slate-600"
          >
            {month.toLocaleDateString("en-US", { month: "long", year: "numeric" })}
            <svg viewBox="0 0 20 20" className="h-4 w-4 text-slate-400" fill="currentColor">
              <path d="M5.23 7.21a.75.75 0 011.06 0L10 10.94l3.71-3.73a.75.75 0 111.06 1.06l-4.24 4.25a.75.75 0 01-1.06 0L5.23 8.27a.75.75 0 010-1.06z" />
            </svg>
          </button>

          {pickerOpen && (
            <>
              <button
                aria-label="Close month picker"
                onClick={() => setPickerOpen(false)}
                className="fixed inset-0 z-40 cursor-default"
              />
              <div className="absolute left-0 top-full z-50 mt-1 w-60 rounded-xl border border-slate-200 bg-white p-3 shadow-lg">
                <div className="mb-2 flex items-center justify-between">
                  <button
                    onClick={() => setPickerYear((y) => y - 1)}
                    aria-label="Previous year"
                    className="rounded p-1 text-slate-500 transition hover:bg-slate-100"
                  >
                    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                      <path d="M12.79 5.23a.75.75 0 010 1.06L9.06 10l3.73 3.71a.75.75 0 11-1.06 1.06l-4.25-4.24a.75.75 0 010-1.06l4.25-4.24a.75.75 0 011.06 0z" />
                    </svg>
                  </button>
                  <span className="text-sm font-semibold text-slate-800">{pickerYear}</span>
                  <button
                    onClick={() => setPickerYear((y) => y + 1)}
                    aria-label="Next year"
                    className="rounded p-1 text-slate-500 transition hover:bg-slate-100"
                  >
                    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                      <path d="M7.21 14.77a.75.75 0 010-1.06L10.94 10 7.21 6.29a.75.75 0 111.06-1.06l4.25 4.24a.75.75 0 010 1.06l-4.25 4.24a.75.75 0 01-1.06 0z" />
                    </svg>
                  </button>
                </div>
                <div className="grid grid-cols-3 gap-1">
                  {MONTHS.map((label, i) => {
                    const active = month.getMonth() === i && month.getFullYear() === pickerYear;
                    return (
                      <button
                        key={label}
                        onClick={() => {
                          setMonth(new Date(pickerYear, i, 1));
                          setPickerOpen(false);
                        }}
                        className={`rounded-md px-2 py-1.5 text-sm font-medium transition ${
                          active
                            ? "bg-brand text-white"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => setMonth(startOfMonth(new Date()))}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50"
          >
            Today
          </button>
          <button
            onClick={() => setMonth((m) => new Date(m.getFullYear(), m.getMonth() - 1, 1))}
            aria-label="Previous month"
            className="rounded-lg p-1.5 text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
              <path d="M12.79 5.23a.75.75 0 010 1.06L9.06 10l3.73 3.71a.75.75 0 11-1.06 1.06l-4.25-4.24a.75.75 0 010-1.06l4.25-4.24a.75.75 0 011.06 0z" />
            </svg>
          </button>
          <button
            onClick={() => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + 1, 1))}
            aria-label="Next month"
            className="rounded-lg p-1.5 text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
              <path d="M7.21 14.77a.75.75 0 010-1.06L10.94 10 7.21 6.29a.75.75 0 111.06-1.06l4.25 4.24a.75.75 0 010 1.06l-4.25 4.24a.75.75 0 01-1.06 0z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Grid — horizontally scrollable on narrow screens so cells stay legible. */}
      <div ref={scroller} className="overflow-x-auto">
        <div className="min-w-[680px]">
          <div className="grid grid-cols-7 border-b border-slate-200">
            {WEEKDAYS.map((d) => (
              <div key={d} className="px-2 py-1.5 text-xs font-semibold text-slate-500">
                {d}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-7">
            {cells.map((d) => {
              const iso = toISO(d);
              const inMonth = d.getMonth() === month.getMonth();
              const isToday = iso === todayISO;
              const dayTasks = byDate.get(iso) ?? [];
              const isDrop = dragOver === iso;
              return (
                <div
                  key={iso}
                  data-day={iso}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (canEdit) setDragOver(iso);
                  }}
                  onDragLeave={() => setDragOver((cur) => (cur === iso ? null : cur))}
                  onDrop={(e) => onDrop(e, iso)}
                  className={`min-h-[104px] border-b border-r border-slate-100 p-1.5 transition-colors ${
                    // One background at a time: alongside bg-white, the drop highlight would not show.
                    isDrop ? "bg-slate-200/70" : inMonth ? "bg-white" : "bg-slate-50/60"
                  }`}
                >
                  <div className="mb-1 flex justify-end">
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded-full text-xs font-medium ${
                        isToday
                          ? "bg-brand text-white"
                          : inMonth
                            ? "text-slate-600"
                            : "text-slate-300"
                      }`}
                    >
                      {d.getDate()}
                    </span>
                  </div>
                  <div className="space-y-1">
                    {dayTasks.slice(0, 3).map((task) => chip(task, !inMonth))}
                    {dayTasks.length > 3 && (
                      <div className="px-1 text-[10px] font-medium text-slate-400">
                        +{dayTasks.length - 3} more
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* "No deadline" tray — a drop target: drag a dated task here to clear its deadline,
          or drag one of these onto a day to schedule it. */}
      {(unscheduled.length > 0 || canEdit) && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (canEdit) setDragOver("tray");
          }}
          onDragLeave={() => setDragOver((cur) => (cur === "tray" ? null : cur))}
          onDrop={(e) => onDrop(e, null)}
          data-day="tray"
          className={`rounded-xl border border-dashed p-3 transition-colors ${
            dragOver === "tray" ? "border-slate-400 bg-slate-200/70" : "border-slate-200 bg-white/60"
          }`}
        >
          <p className="mb-2 text-xs font-semibold text-slate-500">
            No deadline ({unscheduled.length})
            {canEdit && (
              <span className="font-normal text-slate-400">
                {" "}
                {touchScreen
                  ? "— press and hold a task, then drag it here to clear its deadline or onto a day to schedule it"
                  : "— drag a task here to clear its deadline, or onto a day to schedule it"}
              </span>
            )}
          </p>
          {unscheduled.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {unscheduled.map((task) => (
                <div key={task.id} className="w-48">
                  {chip(task)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* The held task, following the finger. */}
      {touchDrag && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-50 max-w-[200px] truncate rounded-md bg-ink px-2.5 py-1.5 text-xs font-medium text-white shadow-lg"
          style={{ left: touchDrag.x - 24, top: touchDrag.y - 44 }}
        >
          {touchDrag.task.description}
        </div>
      )}
    </div>
  );
}
