/** Small shared pieces. Kept deliberately few — this app is mostly forms and
 *  tables, and a component library would be more code than it saves. */
import type { ReactNode } from "react";

export function Badge({ kind, children }: { kind?: string; children: ReactNode }) {
  return <span className={`badge${kind ? ` badge-${kind}` : ""}`}>{children}</span>;
}

export function Alert({ kind, children }: { kind: "error" | "success" | "info"; children: ReactNode }) {
  return <div className={`alert alert-${kind}`}>{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="Loading" />;
}

export function LoadingScreen() {
  return (
    <div className="center-screen">
      <Spinner />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint ? <div className="faint" style={{ marginTop: 5 }}>{hint}</div> : null}
    </div>
  );
}

/** Money, from integer minor units. Never float arithmetic — 199000 paise is
 *  exactly ₹1,990, and 1990.0000000002 is not a price anyone wants to read. */
export function formatPrice(cents: number, currency: string): string {
  if (cents === 0) return "Free";
  const symbol = currency === "INR" ? "₹" : currency === "USD" ? "$" : `${currency} `;
  const major = Math.floor(cents / 100);
  const minor = cents % 100;
  const grouped = major.toLocaleString(currency === "INR" ? "en-IN" : "en-US");
  return minor ? `${symbol}${grouped}.${String(minor).padStart(2, "0")}` : `${symbol}${grouped}`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 2592000) return `${Math.floor(seconds / 86400)}d ago`;
  return formatDate(iso);
}

/** A rough device label from a user-agent string, for the sessions list.
 *  Precise UA parsing is a losing game; "Chrome on macOS" is enough for someone
 *  deciding whether they recognise a login. */
export function describeAgent(agent: string | null): string {
  if (!agent) return "Unknown device";
  const browser =
    /Edg\//.test(agent) ? "Edge"
    : /OPR\//.test(agent) ? "Opera"
    : /Firefox\//.test(agent) ? "Firefox"
    : /Chrome\//.test(agent) ? "Chrome"
    : /Safari\//.test(agent) ? "Safari"
    : /curl|httpx|python/i.test(agent) ? "API client"
    : "Browser";
  const os =
    /Windows/.test(agent) ? "Windows"
    : /Macintosh|Mac OS/.test(agent) ? "macOS"
    : /Android/.test(agent) ? "Android"
    : /iPhone|iPad/.test(agent) ? "iOS"
    : /Linux/.test(agent) ? "Linux"
    : "";
  return os ? `${browser} on ${os}` : browser;
}
