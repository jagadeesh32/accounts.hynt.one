/**
 * Sign in.
 *
 * When a platform sent the user here, `?next=` holds the original /oauth/authorize
 * URL. On success the browser goes straight back to it, the SSO cookie is now
 * present, and the platform receives its code without the user seeing this page
 * again. That replay is the whole hand-off.
 */
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useSession } from "../lib/session";
import { Alert, Field, Spinner } from "../components/ui";

/** Only allow a `next` that points back at this origin's OAuth endpoint.
 *  An unchecked `next` makes the login page an open redirect — the exact thing
 *  the authorize endpoint refuses to be. */
function safeNext(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin) return null;
    if (!url.pathname.startsWith("/oauth/")) return null;
    return url.toString();
  } catch {
    return null;
  }
}

export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useSession();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const next = safeNext(params.get("next"));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login(email.trim(), password);
      if (next) {
        // A full navigation, not a router push: the destination is the identity
        // provider's own authorize endpoint, not a route in this SPA.
        window.location.assign(next);
        return;
      }
      await refresh();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <div className="auth-brand">
          <span className="brand-mark">H</span>
          <span style={{ fontWeight: 700, fontSize: 16 }}>Hynt</span>
        </div>
        <h1 className="auth-title">Sign in</h1>
        <p className="auth-sub">
          {next ? "Continue to the app you were opening." : "One account for every Hynt platform."}
        </p>

        {error ? <Alert kind="error">{error}</Alert> : null}

        <Field label="Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </Field>

        <Field label="Password">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>

        <div style={{ marginTop: 18 }}>
          <button className="btn btn-primary btn-block" disabled={busy || !email || !password}>
            {busy ? <Spinner /> : null}
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>

        <div className="auth-foot">
          <Link to="/forgot-password">Forgot your password?</Link>
        </div>
      </form>
    </div>
  );
}
