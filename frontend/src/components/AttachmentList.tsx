"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { Attachment, TaskMeta } from "@/lib/types";

interface Props {
  taskId: number;
  canEdit: boolean;
  onMetaChange: (meta: Partial<TaskMeta>) => void;
}

export default function AttachmentList({ taskId, canEdit, onMetaChange }: Props) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const onMetaRef = useRef(onMetaChange);
  onMetaRef.current = onMetaChange;

  const sync = (list: Attachment[]) => {
    setAttachments(list);
    onMetaRef.current({ attachment_count: list.length });
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listAttachments(taskId)
      .then((list) => {
        if (cancelled) return;
        setAttachments(list);
        onMetaRef.current({ attachment_count: list.length });
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      let list = attachments;
      for (const file of Array.from(files)) {
        const created = await api.uploadAttachment(taskId, file);
        list = [...list, created];
        sync(list);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const download = async (att: Attachment) => {
    setError(null);
    try {
      await api.downloadAttachment(att.id, att.filename);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (id: number) => {
    const prev = attachments;
    sync(attachments.filter((a) => a.id !== id));
    try {
      await api.deleteAttachment(id);
    } catch (err) {
      sync(prev);
      setError((err as Error).message);
    }
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-700">Attachments</span>
        {canEdit && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => handleFiles(e.target.files)}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50 disabled:opacity-50"
            >
              {uploading ? (
                <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <PaperclipIcon className="h-3.5 w-3.5" />
              )}
              {uploading ? "Uploading…" : "Attach file"}
            </button>
          </>
        )}
      </div>

      {error && <p className="mb-2 rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-600">{error}</p>}

      {loading ? (
        <p className="py-1 text-sm text-slate-400">Loading…</p>
      ) : attachments.length === 0 ? (
        <p className="py-1 text-sm text-slate-400">
          {canEdit ? "No files attached. Up to 10 MB each." : "No files attached."}
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-100">
          {attachments.map((att) => (
            <li key={att.id} className="group/att flex items-center gap-2.5 px-2.5 py-2">
              <PaperclipIcon className="h-4 w-4 shrink-0 text-slate-400" />
              <button
                type="button"
                onClick={() => download(att)}
                title={`Download ${att.filename}`}
                className="min-w-0 flex-1 truncate text-left text-sm text-slate-700 hover:text-slate-900 hover:underline"
              >
                {att.filename}
              </button>
              <span className="shrink-0 text-xs text-slate-400">{formatBytes(att.size)}</span>
              {canEdit && (
                <button
                  type="button"
                  onClick={() => remove(att.id)}
                  aria-label="Delete attachment"
                  className="shrink-0 rounded p-0.5 text-slate-300 opacity-0 transition hover:bg-slate-100 hover:text-rose-500 group-hover/att:opacity-100 [@media(hover:none)]:opacity-100"
                >
                  <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor">
                    <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                  </svg>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PaperclipIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"
      />
    </svg>
  );
}
