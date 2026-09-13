import {
  createContext, useCallback, useContext, useEffect, useLayoutEffect,
  useMemo, useRef, useState, type ReactNode,
} from "react";

/* =========================================================
   Icons — one stroke-based set on a 24 grid
   ========================================================= */
const ICONS = {
  "arrow-right": "M5 12h14M13 6l6 6-6 6",
  "arrow-up-right": "M7 17 17 7M8 7h9v9",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M5.5 11h13a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z",
  shield: "M12 3 5 5.5v5.7c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V5.5L12 3Z",
  "shield-check": "M12 3 5 5.5v5.7c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V5.5L12 3ZM9 11.5l2 2 4-4",
  "shield-off": "M12 3 5 5.5v5.7c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V5.5L12 3ZM9.5 9.5l5 5M14.5 9.5l-5 5",
  key: "M14.5 9.5a3.5 3.5 0 1 1 3.4 3.5L17 14h-2v2h-2v2H8v-3l6.5-6.5Z",
  monitor: "M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM9 20h6M12 16v4",
  smartphone: "M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM11 18h2",
  tablet: "M7 3h10a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM11.5 18h1",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM3 12h18M12 3c2.5 2.5 3.8 5.6 3.8 9S14.5 18.5 12 21c-2.5-2.5-3.8-5.6-3.8-9S9.5 5.5 12 3Z",
  search: "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14ZM20 20l-4.2-4.2",
  plus: "M12 5v14M5 12h14",
  copy: "M9 9V5.5A1.5 1.5 0 0 1 10.5 4h8A1.5 1.5 0 0 1 20 5.5v8a1.5 1.5 0 0 1-1.5 1.5H15M4 10.5A1.5 1.5 0 0 1 5.5 9h8a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5h-8A1.5 1.5 0 0 1 4 18.5v-8Z",
  check: "M5 12.5 10 17.5 19 7",
  x: "M6 6l12 12M18 6 6 18",
  "chevron-down": "m6 9 6 6 6-6",
  eye: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12ZM12 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z",
  "eye-off": "M4 4l16 16M10 6a9.8 9.8 0 0 1 2-.2c6 0 9.5 6.2 9.5 6.2a17 17 0 0 1-3 3.7M6.5 7.7A16.6 16.6 0 0 0 2.5 12S6 18.2 12 18.2c1 0 2-.2 2.9-.5M9.9 9.9a2.5 2.5 0 0 0 3.5 3.5",
  "log-out": "M14 4h5a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-5M4 12h11M8.5 7.5 4 12l4.5 4.5",
  warning: "M12 4 2.8 19.5a1 1 0 0 0 .9 1.5h16.6a1 1 0 0 0 .9-1.5L12 4ZM12 10v4M12 17.5v.5",
  users: "M8.5 11a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7ZM2.5 20c0-3 2.7-5 6-5s6 2 6 5M16 4.4a3.5 3.5 0 0 1 0 6.7M17.5 15.4c2.4.6 4 2.4 4 4.6",
  server: "M4 4h16a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1ZM4 14h16a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1ZM7.5 7h.5M7.5 17h.5",
  activity: "M3 12h4l3-7 4 14 3-7h4",
  layers: "m12 3 9 5-9 5-9-5 9-5ZM3 13l9 5 9-5M3 17l9 5 9-5",
  link: "M9.5 14.5 14.5 9.5M8 11l-2.5 2.5a3.5 3.5 0 0 0 5 5L13 16M16 13l2.5-2.5a3.5 3.5 0 0 0-5-5L11 8",
  ban: "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18ZM5.7 5.7l12.6 12.6",
  "user-plus": "M9 11a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7ZM2.5 20c0-3 2.7-5 6-5s6 2 6 5M18 7v6M15 10h6",
  trash: "M4.5 6.5h15M9 6.5V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1.5M6.5 6.5l.8 13a1 1 0 0 0 1 .9h7.4a1 1 0 0 0 1-.9l.8-13M10 10.5v6M14 10.5v6",
  terminal: "m5 8 4 4-4 4M12 16h7M3.5 3.5h17a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-17a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1Z",
  sparkles: "M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6L12 4ZM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15ZM5 15l.6 1.7L7.5 17l-1.9.6L5 19l-.6-1.4L2.5 17l1.9-.3L5 15Z",
  fingerprint: "M12 4c-2 0-3.8.7-5.2 1.9M12 8c-1.2 0-2.3.4-3.2 1.1M12 12c-.8 0-1.6.3-2.2.8M12 16c-.5 0-1 .2-1.4.5M18.4 6.6A8 8 0 0 0 15 4.6M20 11a8 8 0 0 0-1.4-3M4.6 8.6A8 8 0 0 0 4 11M16 10a5.3 5.3 0 0 0-1.6-1.6M6 14.5A8 8 0 0 1 5.4 11M8 18.4A8 8 0 0 1 6.7 16M13 20a8 8 0 0 1-3-.6M17 14.5a8 8 0 0 1-.8 2.6",
  clock: "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18ZM12 7.5V12l3 2",
  mail: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM3.5 6.5 12 13l8.5-6.5",
  refresh: "M20 5v5h-5M4 19v-5h5M19.4 14a8 8 0 0 1-13 3.5L4 14M4.6 10a8 8 0 0 1 13-3.5L20 10",
  hash: "M6 9h13M5 15h13M10 4l-2 16M16 4l-2 16",
  "clipboard-list": "M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1ZM8 6H6a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-2M8.5 12h7M8.5 16h5",
  "shield-alert": "M12 3 5 5.5v5.7c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V5.5L12 3ZM12 9v4M12 16.5v.5",
  "grid-apps": "M4 4h6v6H4V4ZM14 4h6v6h-6V4ZM4 14h6v6H4v-6ZM14 14h6v6h-6v-6Z",
  history: "M4 12a8 8 0 1 1 2.3 5.7M4 12V7M4 12h5M12 8v4l3 2",
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 16, strokeWidth = 1.9 }: { name: IconName; size?: number; strokeWidth?: number }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    >
      <path d={ICONS[name]} />
    </svg>
  );
}

/* =========================================================
   Avatar — deterministic gradient per person
   ========================================================= */
const AVATAR_RAMPS: Array<[string, string]> = [
  ["#5b8dff", "#22d3ee"],
  ["#8a7bff", "#5b8dff"],
  ["#22d3ee", "#5b8dff"],
  ["#4f8cff", "#8a7bff"],
  ["#38bdf8", "#818cf8"],
  ["#5fe7ff", "#4f8cff"],
];

function hashStr(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}

function initials(name: string, email: string): string {
  const src = name.trim() || email;
  const parts = src.split(/[\s._@-]+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function Avatar({ name = "", email = "", size = "md" }: { name?: string; email?: string; size?: "sm" | "md" | "lg" }) {
  const [a, b] = AVATAR_RAMPS[hashStr(email || name || "?") % AVATAR_RAMPS.length];
  return (
    <span
      className={`avatar ${size}`}
      style={{ background: `linear-gradient(135deg, ${a}, ${b})` }}
      aria-hidden="true"
    >
      {initials(name, email)}
    </span>
  );
}

/* =========================================================
   Toasts
   ========================================================= */
interface Toast {
  id: number;
  kind: "ok" | "error" | "info";
  title: string;
  desc?: string;
  leaving?: boolean;
}

const ToastCtx = createContext<{
  ok: (title: string, desc?: string) => void;
  error: (title: string, desc?: string) => void;
  info: (title: string, desc?: string) => void;
}>({ ok: () => {}, error: () => {}, info: () => {} });

export function useToast() {
  return useContext(ToastCtx);
}

const TOAST_TTL = 5000;
let toastSeq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<number, number>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((ts) => ts.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    const timer = window.setTimeout(() => {
      setToasts((ts) => ts.filter((t) => t.id !== id));
      timers.current.delete(id);
    }, 240);
    timers.current.set(id, timer);
  }, []);

  const push = useCallback((kind: Toast["kind"], title: string, desc?: string) => {
    const id = ++toastSeq;
    setToasts((ts) => [...ts.slice(-3), { id, kind, title, desc }]);
    const timer = window.setTimeout(() => dismiss(id), kind === "error" ? 8000 : TOAST_TTL);
    timers.current.set(id, timer);
  }, [dismiss]);

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);

  const api = useMemo(
    () => ({
      ok: (title: string, desc?: string) => push("ok", title, desc),
      error: (title: string, desc?: string) => push("error", title, desc),
      info: (title: string, desc?: string) => push("info", title, desc),
    }),
    [push],
  );

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div className="toast-host" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind} ${t.leaving ? "leaving" : ""}`}>
            <span className="ticon">
              <Icon name={t.kind === "ok" ? "check" : t.kind === "error" ? "warning" : "sparkles"} size={14} strokeWidth={2.4} />
            </span>
            <div className="tbody">
              <div className="ttitle">{t.title}</div>
              {t.desc && <div className="tdesc">{t.desc}</div>}
            </div>
            <button className="tx" onClick={() => dismiss(t.id)} aria-label="Dismiss">
              <Icon name="x" size={13} />
            </button>
            <span className="tbar" style={{ animationDuration: t.kind === "error" ? "8s" : "5s" }} />
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* =========================================================
   Modal + confirm dialog
   ========================================================= */
export function Modal({
  open, onClose, tone = "info", icon, title, children, footer,
}: {
  open: boolean; onClose: () => void; tone?: "info" | "danger"; icon?: IconName;
  title: string; children?: ReactNode; footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-veil" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="mhead">
          <span className={`micon ${tone}`}>
            <Icon name={icon ?? (tone === "danger" ? "warning" : "sparkles")} size={19} strokeWidth={2} />
          </span>
          <div>
            <h2>{title}</h2>
            <div className="mdesc">{children}</div>
          </div>
        </div>
        <div className="mfoot">{footer}</div>
      </div>
    </div>
  );
}

export function Confirm({
  open, onClose, onConfirm, tone = "danger", icon, title, children, confirmLabel = "Confirm", busy,
}: {
  open: boolean; onClose: () => void; onConfirm: () => void;
  tone?: "info" | "danger"; icon?: IconName; title: string; children?: ReactNode;
  confirmLabel?: string; busy?: boolean;
}) {
  return (
    <Modal
      open={open} onClose={onClose} tone={tone} icon={icon} title={title}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button
            className={`btn ${tone === "danger" ? "danger" : "primary"}`} onClick={onConfirm} disabled={busy}
          >
            {busy ? <span className="dots" /> : null}
            {confirmLabel}
          </button>
        </>
      }
    >
      {children}
    </Modal>
  );
}

/* =========================================================
   Copy button
   ========================================================= */
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={`copy-btn ${copied ? "copied" : ""}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
        } catch {
          const ta = document.createElement("textarea");
          ta.value = value;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
        }
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }}
    >
      <Icon name={copied ? "check" : "copy"} size={12} strokeWidth={2.2} />
      {copied ? "Copied" : label}
    </button>
  );
}

/* =========================================================
   Password field with visibility toggle
   ========================================================= */
export function PasswordField({
  value, onChange, placeholder, autoComplete, leadIcon = "lock", minLength, autoFocus, required,
  onKeyDown, onKeyUp,
}: {
  value: string; onChange: (v: string) => void; placeholder?: string;
  autoComplete?: string; leadIcon?: IconName; minLength?: number; autoFocus?: boolean; required?: boolean;
  onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>;
  onKeyUp?: React.KeyboardEventHandler<HTMLInputElement>;
}) {
  const [show, setShow] = useState(false);
  return (
    <span className="input-wrap">
      <span className="lead-icon"><Icon name={leadIcon} size={15} /></span>
      <input
        type={show ? "text" : "password"} value={value} placeholder={placeholder}
        autoComplete={autoComplete} minLength={minLength} autoFocus={autoFocus} required={required}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown} onKeyUp={onKeyUp}
      />
      <button
        type="button" className="btn ghost icon trail" tabIndex={-1}
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Hide password" : "Show password"}
      >
        <Icon name={show ? "eye-off" : "eye"} size={15} />
      </button>
    </span>
  );
}

/* =========================================================
   Segmented control with sliding pill
   ========================================================= */
export interface SegOption<T extends string> { value: T; label: string; icon?: IconName; count?: number }

export function Segmented<T extends string>({ options, value, onChange }: {
  options: SegOption<T>[]; value: T; onChange: (v: T) => void;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [pill, setPill] = useState({ x: 0, w: 0, ready: false });

  useLayoutEffect(() => {
    const el = refs.current[value];
    if (el) setPill({ x: el.offsetLeft, w: el.offsetWidth, ready: true });
  }, [value, options]);

  return (
    <div className="segmented" role="tablist">
      <span
        className={`seg-pill ${pill.ready ? "ready" : ""}`}
        style={{ width: pill.w, transform: `translateX(${pill.x}px)` }}
      />
      {options.map((o) => (
        <button
          key={o.value} role="tab" aria-selected={o.value === value}
          ref={(el) => { refs.current[o.value] = el; }}
          className={o.value === value ? "on" : ""}
          onClick={() => onChange(o.value)}
        >
          {o.icon && <Icon name={o.icon} size={14} />}
          {o.label}
          {o.count !== undefined && <span className="count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

/* =========================================================
   Misc helpers
   ========================================================= */
export function Empty({ icon = "grid-apps", title, hint }: { icon?: IconName; title: string; hint?: string }) {
  return (
    <div className="empty">
      <span className="eicon"><Icon name={icon} size={21} /></span>
      <h3>{title}</h3>
      {hint && <p>{hint}</p>}
    </div>
  );
}

export function Skeleton({ w, h, style }: { w?: number | string; h?: number | string; style?: React.CSSProperties }) {
  return <span className="skeleton" style={{ width: w, height: h, ...style }} />;
}

export function relTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 45e3) return "just now";
  if (diff < 3600e3) return `${Math.max(1, Math.floor(diff / 60e3))}m ago`;
  if (diff < 86400e3) return `${Math.floor(diff / 3600e3)}h ago`;
  if (diff < 7 * 86400e3) return `${Math.floor(diff / 86400e3)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function deviceOf(agent: string | null): { icon: IconName; label: string } {
  if (!agent) return { icon: "monitor", label: "Unknown device" };
  const browser = /Edg\//.test(agent) ? "Edge"
    : /OPR\//.test(agent) ? "Opera"
    : /Chrome\//.test(agent) ? "Chrome"
    : /Safari\//.test(agent) ? "Safari"
    : /Firefox\//.test(agent) ? "Firefox"
    : "Browser";
  const os = /Windows/.test(agent) ? "Windows"
    : /Mac OS X/.test(agent) ? "macOS"
    : /Android/.test(agent) ? "Android"
    : /iPhone|iPad|iPod/.test(agent) ? "iOS"
    : /Linux/.test(agent) ? "Linux"
    : "";
  const device = /iPhone|Android.*Mobile|Mobile/.test(agent) ? "smartphone"
    : /iPad|Tablet/.test(agent) ? "tablet"
    : "monitor";
  return { icon: device as IconName, label: os ? `${browser} · ${os}` : browser };
}

export function passwordScore(pw: string): 0 | 1 | 2 | 3 | 4 {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 10) score++;
  if (pw.length >= 14) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
  return Math.min(4, score) as 0 | 1 | 2 | 3 | 4;
}

export const STRENGTH_LABEL = ["", "Weak", "Fair", "Good", "Strong"];
