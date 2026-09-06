/**
 * The banner every console page shows after an action, and the wrapper that
 * fills it in.
 *
 * Splitting the console into a page per concern multiplied the same twelve
 * lines of "try, set a message, reload" by nine. This is that, once. `act`
 * deliberately reloads *after* a success and not after a failure: a failed
 * write changed nothing, and refetching would only make the row flicker.
 */
import { useCallback, useState } from "react";
import { ApiError } from "../api";

export interface Note { kind: "ok" | "error"; text: string }

export function useNote() {
  const [note, setNote] = useState<Note | null>(null);

  const act = useCallback(
    async (fn: () => Promise<unknown>, ok: string, reload?: () => Promise<unknown> | void) => {
      setNote(null);
      try {
        await fn();
        setNote({ kind: "ok", text: ok });
        await reload?.();
        return true;
      } catch (err) {
        // ApiError carries the server's own `detail`, which is written for a
        // person; anything else is a network or parse failure and gets a
        // generic line rather than a stack trace on screen.
        setNote({
          kind: "error",
          text: err instanceof ApiError ? err.message : "Something went wrong.",
        });
        return false;
      }
    },
    [],
  );

  return { note, setNote, act };
}

export function NoteBanner({ note }: { note: Note | null }) {
  if (!note) return null;
  return <div className={`alert ${note.kind === "ok" ? "ok" : "error"}`}>{note.text}</div>;
}
