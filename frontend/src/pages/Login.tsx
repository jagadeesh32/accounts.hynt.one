import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError, type Me } from "../api";

/**
 * The one password form in the estate.
 *
 * `next` carries the whole /oauth/authorize request the user was bounced from,
 * so signing in lands them back in the flow rather than on the launcher.
 */
export function LoginPage({ me, onSignedIn }: { me: Me | null; onSignedIn: () => void }) {
  const [params] = useSearchParams();
  const next = params.get("next") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [mfaRequired, setMfaRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in and sent here by a platform: complete the flow silently
  // rather than asking for a password that is not needed.
  useEffect(() => {
    if (me && next.startsWith("/oauth/")) window.location.replace(next);
  }, [me, next]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ mfa_required?: boolean }>("/api/v1/auth/login", {
        email: email.trim(),
        password,
        otp: otp || null,
      });
      if (result.mfa_required) {
        setMfaRequired(true);
        setBusy(false);
        return;
      }
      // A /oauth/… next is a server route, not a React one: it must be a real
      // navigation or the SPA router would try to render it and 404.
      if (next.startsWith("/oauth/")) {
        window.location.replace(next);
        return;
      }
      onSignedIn();
      window.location.replace(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <span className="brand-mark big">H</span>
          <h1>Sign in to Hynt</h1>
          <p className="muted">One account for Terminal, X-Terminal and Intelligence.</p>
        </div>

        {error && <div className="alert error">{error}</div>}

        <label className="field">
          <span>Email</span>
          <input
            type="email" value={email} autoFocus required autoComplete="username"
            onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com"
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password" value={password} required autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        {mfaRequired && (
          <label className="field">
            <span>Verification code</span>
            <input
              type="text" value={otp} autoFocus inputMode="numeric" maxLength={6}
              placeholder="123456" onChange={(e) => setOtp(e.target.value)}
            />
            <small className="muted">From your authenticator app.</small>
          </label>
        )}

        <button className="btn primary wide" type="submit" disabled={busy}>
          {busy ? "Signing in…" : mfaRequired ? "Verify and continue" : "Sign in"}
        </button>

        <p className="fineprint muted">
          Signing in here signs you in across every Hynt platform.
        </p>
      </form>
    </div>
  );
}
