/**
 * A slide-over editor.
 *
 * Platforms, OAuth clients and plans are all "a handful of fields, edited in
 * place, saved or abandoned" — a modal each would triple the chrome for no gain,
 * so they share this one. It is deliberately dumb: it owns no form state and
 * validates nothing. The page that opens it owns the draft, which is what lets a
 * caller decide that closing means "discard" without the drawer having an
 * opinion.
 *
 * Escape closes and focus moves in on open, because a panel that traps neither
 * is a panel a keyboard cannot leave.
 */
import { useEffect, useMemo, useRef, type ReactNode } from "react";

export function Drawer({
  open,
  title,
  subtitle,
  onClose,
  onSave,
  saveLabel = "Save",
  busy = false,
  children,
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  onSave?: () => void;
  saveLabel?: string;
  busy?: boolean;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // The first field, not the panel: the point of opening an editor is to type.
    panel.current?.querySelector<HTMLElement>("input, select, textarea")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="dw-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dw" role="dialog" aria-modal="true" aria-label={title} ref={panel}>
        <header className="dw-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          <button className="btn ghost small" onClick={onClose} aria-label="Close">Close</button>
        </header>

        <div className="dw-body">{children}</div>

        {onSave && (
          <footer className="dw-foot">
            <button className="btn ghost" onClick={onClose}>Cancel</button>
            <button className="btn primary" onClick={onSave} disabled={busy}>
              {busy ? "Saving…" : saveLabel}
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}

/** A labelled field. Exists so every drawer lays its form out the same way. */
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="dw-field">
      <span className="dw-label">{label}</span>
      {children}
      {hint && <span className="dw-hint">{hint}</span>}
    </label>
  );
}

/**
 * A textarea that edits a list as one-per-line.
 *
 * Redirect URIs and entitlements are both short string lists where the
 * whitespace between entries is meaningless, and a line-per-entry box is the
 * one editor that never needs an "add row" button. Blank lines are dropped on
 * the way out so a trailing newline cannot register an empty URI — which the
 * authorize endpoint would then never match, in a way that is invisible on screen.
 */
export function ListField({
  label,
  hint,
  value,
  onChange,
  rows = 4,
  placeholder,
}: {
  label: string;
  hint?: string;
  value: string[];
  onChange: (next: string[]) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <textarea
        rows={rows}
        className="dw-area mono"
        placeholder={placeholder}
        value={value.join("\n")}
        onChange={(e) =>
          onChange(e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))
        }
      />
    </Field>
  );
}

/**
 * A JSON object editor that refuses to hand back invalid JSON.
 *
 * Plan limits are a free-form dict, so the honest editor is a JSON box. Keeping
 * the raw text in the caller's draft (rather than reformatting on every
 * keystroke) is what lets someone type a half-finished object without the
 * cursor jumping; `onValidity` lets the drawer disable Save until it parses,
 * so a typo cannot be saved as an empty dict and silently drop a plan's limits.
 */
export function JsonField({
  label,
  hint,
  text,
  onText,
  onValidity,
}: {
  label: string;
  hint?: string;
  text: string;
  onText: (next: string) => void;
  onValidity: (ok: boolean) => void;
}) {
  const problem = useMemo<string | null>(() => {
    try {
      const parsed = JSON.parse(text || "{}");
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        return "Must be a JSON object, e.g. {\"seats\": 5}";
      }
      return null;
    } catch {
      return "Not valid JSON yet";
    }
  }, [text]);

  // In an effect, not in render: reporting validity is a parent state update,
  // and doing that while rendering is what turns a typo into a render loop.
  useEffect(() => {
    onValidity(problem === null);
  }, [problem, onValidity]);

  return (
    <Field label={label} hint={hint}>
      <textarea
        rows={4}
        className={`dw-area mono ${problem ? "bad" : ""}`}
        value={text}
        onChange={(e) => onText(e.target.value)}
      />
      {problem && <span className="dw-bad">{problem}</span>}
    </Field>
  );
}
