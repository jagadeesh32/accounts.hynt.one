import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError, type Me } from "../api";
import { Icon, PasswordField } from "../ui";

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
  const [shakeKey, setShakeKey] = useState(0);

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
      setShakeKey((k) => k + 1);
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <span className="brand-mark big">H</span>
          <h1>Sign in to Hynt</h1>
          <p className="sub">One account for Terminal, X-Terminal and Intelligence.</p>
        </div>

        {error && (
          <div key={shakeKey} className="alert error shake">
            <Icon name="warning" size={15} />
            <span>{error}</span>
          </div>
        )}

        <label className="field">
          <span><Icon name="mail" size={13} />Email</span>
          <span className="input-wrap">
            <span className="lead-icon"><Icon name="mail" size={15} /></span>
            <input
              type="email" value={email} autoFocus required autoComplete="username"
              onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com"
            />
          </span>
        </label>

        <label className="field">
          <span><Icon name="lock" size={13} />Password</span>
          <PasswordField
            value={password} onChange={setPassword} required
            autoComplete="current-password" placeholder="Your password"
          />
        </label>

        {mfaRequired && (
          <label className="field mfa-reveal">
            <span><Icon name="fingerprint" size={13} />Verification code</span>
            <input
              type="text" value={otp} autoFocus inputMode="numeric" maxLength={6}
              className="otp-input" placeholder="· · · · · ·"
              onChange={(e) => setOtp(e.target.value.replace(/[^\d]/g, ""))}
            />
            <small className="muted">Enter the 6-digit code from your authenticator app.</small>
          </label>
        )}

        <button className="btn primary wide" type="submit" disabled={busy}>
          {busy ? "Signing in" : mfaRequired ? "Verify and continue" : "Sign in"}
          {!busy && <Icon name="arrow-right" size={15} />}
          {busy && <span className="dots" />}
        </button>

        <p className="fineprint">
          <Icon name="shield-check" size={13} />
          Signing in here signs you in across every Hynt platform.
        </p>
      </form>
    </div>
  );
}
