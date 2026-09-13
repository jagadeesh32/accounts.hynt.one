import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError, type Me } from "../api";
import { AppearanceButton } from "../widgets/AppearancePanel";
import { Icon, PasswordField, type IconName } from "../ui";

/** The desks one account unlocks — mirrors the estate this host is IdP for. */
const PLATFORMS: { icon: IconName; name: string; blurb: string }[] = [
  { icon: "terminal", name: "Terminal", blurb: "The estate's operations workspace." },
  { icon: "layers", name: "X-Terminal", blurb: "Extended control for power users." },
  { icon: "sparkles", name: "Intelligence", blurb: "Analytics and insight, estate-wide." },
];

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
  const [capsOn, setCapsOn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in and sent here by a platform: complete the flow silently
  // rather than asking for a password that is not needed.
  useEffect(() => {
    if (me && next.startsWith("/oauth/")) window.location.replace(next);
  }, [me, next]);

  /** Caps Lock has no visual on most keyboards; the form says it instead. */
  function trackCaps(event: React.KeyboardEvent) {
    setCapsOn(event.getModifierState?.("CapsLock") ?? false);
  }

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
      {/* ── Showcase — the brand half. Decorative, so hidden from a11y tree. ── */}
      <aside className="login-showcase" aria-hidden="true">
        <div className="showcase-inner">
          <div className="showcase-brand">
            <img className="brand-mark big" src="/logo.svg" width={42} height={42} alt="" draggable={false} />
            <div className="brand-text">
              <span className="brand-name">Hynt</span>
              <span className="brand-tag">Accounts</span>
            </div>
          </div>

          <div className="showcase-mid">
            <div className="showcase-copy">
              <h2>One account.<br />Every Hynt desk.</h2>
              <p>
                Sign in once and every platform recognises you — with your roles,
                plans and audit trail travelling inside the token.
              </p>
            </div>

            <ul className="showcase-list">
              {PLATFORMS.map((p) => (
                <li key={p.name}>
                  <span className="ic"><Icon name={p.icon} size={16} /></span>
                  <div>
                    <strong>{p.name}</strong>
                    <small>{p.blurb}</small>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="showcase-foot">
            <span className="status-dot" />
            <span className="mono">accounts.hynt.one</span>
            <span className="dim">·</span>
            <span>Single sign-on for the Hynt estate</span>
          </div>
        </div>
      </aside>

      {/* ── Form — the credential half. ── */}
      <main className="login-main">
        <div className="login-corner">
          <AppearanceButton />
        </div>

        <div className="login-panel">
          <form className="login-card" onSubmit={submit}>
            <div className="login-lockup">
              <img className="brand-mark" src="/logo.svg" width={34} height={34} alt="Hynt" draggable={false} />
              <div className="brand-text">
                <span className="brand-name">Hynt</span>
                <span className="brand-tag">Accounts</span>
              </div>
            </div>

            <p className="login-eyebrow">Welcome back</p>
            <h1>Sign in to Hynt</h1>
            <p className="login-sub muted">One account for Terminal, X-Terminal and Intelligence.</p>

            {error && (
              <div className="alert error login-alert" role="alert">
                <Icon name="warning" size={15} />
                <span>{error}</span>
              </div>
            )}
            {mfaRequired && !error && (
              <div className="alert ok login-alert">
                <Icon name="shield-check" size={15} />
                <span>Password accepted — enter the code from your authenticator.</span>
              </div>
            )}

            {!mfaRequired && (
              <>
                <label className="field">
                  <span>Email</span>
                  <span className="input-wrap">
                    <span className="lead-icon"><Icon name="mail" size={15} /></span>
                    <input
                      type="email" value={email} autoFocus required autoComplete="username"
                      onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com"
                    />
                  </span>
                </label>

                <label className="field">
                  <div className="label-row">
                    <span>Password</span>
                    {capsOn && (
                      <span className="caps-hint">
                        <Icon name="warning" size={12} /> Caps Lock is on
                      </span>
                    )}
                  </div>
                  <PasswordField
                    value={password} required autoComplete="current-password"
                    onChange={setPassword} onKeyDown={trackCaps} onKeyUp={trackCaps}
                  />
                </label>
              </>
            )}

            {mfaRequired && (
              <label className="field">
                <span>Verification code</span>
                <input
                  className="otp-input" type="text" value={otp} autoFocus inputMode="numeric"
                  maxLength={6} autoComplete="one-time-code" placeholder="••••••"
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  onKeyDown={trackCaps} onKeyUp={trackCaps}
                />
                <small className="muted">Six digits, from your authenticator app.</small>
                {capsOn && (
                  <small className="caps-hint">
                    <Icon name="warning" size={12} /> Caps Lock is on
                  </small>
                )}
              </label>
            )}

            <button className="btn primary wide login-submit" type="submit" disabled={busy}>
              {busy ? (
                <span className="dots">Signing in</span>
              ) : (
                <>
                  {mfaRequired ? "Verify and continue" : "Sign in"}
                  <span className="submit-arrow"><Icon name="arrow-right" size={16} /></span>
                </>
              )}
            </button>

            <p className="fineprint muted">
              Signing in here signs you in across every Hynt platform.
            </p>
          </form>

          <p className="login-foot">
            <Icon name="shield-check" size={13} />
            <span>TOTP multi-factor · Audited sessions · One password for the whole estate</span>
          </p>
        </div>
      </main>
    </div>
  );
}
