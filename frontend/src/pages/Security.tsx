import { useEffect, useState } from "react";
import { api, ApiError, type Me, type SessionRow } from "../api";
import {
  Confirm, CopyButton, Icon, PasswordField, Skeleton, deviceOf, passwordScore, relTime,
  STRENGTH_LABEL, useToast,
} from "../ui";

export function SecurityPage({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const toast = useToast();
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [mfaSetup, setMfaSetup] = useState<{ secret: string } | null>(null);
  const [otp, setOtp] = useState("");
  const [disablePassword, setDisablePassword] = useState("");
  const [confirmRevokeAll, setConfirmRevokeAll] = useState(false);
  const [confirmRevokeOne, setConfirmRevokeOne] = useState<SessionRow | null>(null);
  const [confirmMfaOff, setConfirmMfaOff] = useState(false);

  const loadSessions = () =>
    api.get<{ sessions: SessionRow[] }>("/api/v1/auth/sessions").then((d) => setSessions(d.sessions));

  useEffect(() => {
    void loadSessions();
  }, []);

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      toast.ok(ok);
      await loadSessions();
      onChanged();
    } catch (err) {
      toast.error("Something went wrong", err instanceof ApiError ? err.message : undefined);
    }
  }

  const score = passwordScore(next);

  return (
    <section className="page">
      <header className="page-head">
        <h1>Security</h1>
        <p className="sub">Your password, two-factor and signed-in devices.</p>
      </header>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            <span className="ticon"><Icon name="key" size={16} /></span>
            <h2>Password</h2>
          </div>
        </div>
        <p className="muted">
          Changing your password signs you out of every other device, everywhere.
        </p>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              () => api.post("/api/v1/me/password", { current_password: current, new_password: next }),
              "Password changed. Other devices have been signed out.",
            ).then(() => { setCurrent(""); setNext(""); });
          }}
        >
          <PasswordField
            value={current} onChange={setCurrent} placeholder="Current password"
            autoComplete="current-password" required
          />
          <PasswordField
            value={next} onChange={setNext} placeholder="New password (10+ characters)"
            autoComplete="new-password" minLength={10} required
          />
          <button className="btn primary" type="submit">
            <Icon name="refresh" size={14} />Change
          </button>
        </form>
        {next && (
          <div className="strength">
            <div className="strength-bar">
              {[1, 2, 3, 4].map((i) => (
                <i key={i} className={i <= score ? `on-${score}` : ""} />
              ))}
            </div>
            <div className="strength-label">{STRENGTH_LABEL[score] || "Too short"}</div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            <span className={`ticon ${me.mfa_enabled ? "ok" : ""}`}>
              <Icon name={me.mfa_enabled ? "shield-check" : "shield"} size={16} />
            </span>
            <h2>Two-factor authentication</h2>
          </div>
          {me.mfa_enabled && <span className="chip ok-chip"><span className="dot" />Active</span>}
        </div>

        {me.mfa_enabled ? (
          <>
            <p className="ok-text">Two-factor is on — a second step is required every time you sign in.</p>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              setConfirmMfaOff(true);
            }}>
              <PasswordField
                value={disablePassword} onChange={setDisablePassword}
                placeholder="Confirm your password" autoComplete="current-password" required
              />
              <button className="btn danger" type="submit">
                <Icon name="shield-off" size={14} />Turn off
              </button>
            </form>
          </>
        ) : mfaSetup ? (
          <div className="mfa-steps">
            <div className="mfa">
              <img className="qr" src="/api/v1/me/mfa/qr.png" alt="Two-factor QR code" />
              <div>
                <div className="step" style={{ marginBottom: 6 }}>
                  <span className="step-num">1</span>
                  <div className="sbody">
                    <div className="st">Scan the QR code</div>
                    <div className="sd">With your authenticator app (Google Authenticator, 1Password, Authy…).</div>
                  </div>
                </div>
                <div className="step">
                  <span className="step-num">2</span>
                  <div className="sbody">
                    <div className="st">Or enter this key by hand</div>
                    <span className="secret">
                      {mfaSetup.secret}
                      <CopyButton value={mfaSetup.secret} />
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post("/api/v1/me/mfa/enable", { otp }), "Two-factor is on.")
                .then(() => { setMfaSetup(null); setOtp(""); });
            }}>
              <span className="input-wrap" style={{ flex: "1 1 170px" }}>
                <span className="lead-icon"><Icon name="fingerprint" size={15} /></span>
                <input
                  className="otp-input" inputMode="numeric" maxLength={6} placeholder="· · · · · ·"
                  value={otp} required style={{ textAlign: "left" }}
                  onChange={(e) => setOtp(e.target.value.replace(/[^\d]/g, ""))}
                />
              </span>
              <button className="btn primary" type="submit">
                <Icon name="shield-check" size={14} />Confirm &amp; turn on
              </button>
            </form>
          </div>
        ) : (
          <>
            <p className="muted">Add a second step when signing in — even if your password leaks, nobody gets in.</p>
            <button className="btn primary" onClick={() => {
              void api.post<{ secret: string }>("/api/v1/me/mfa/setup").then(setMfaSetup);
            }}>
              <Icon name="shield-check" size={14} />Set up two-factor
            </button>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            <span className="ticon"><Icon name="monitor" size={16} /></span>
            <h2>Signed-in devices</h2>
          </div>
          <button className="btn ghost" onClick={() => setConfirmRevokeAll(true)}>
            <Icon name="log-out" size={14} />Sign out everywhere else
          </button>
        </div>

        {!sessions ? (
          <div className="session-list" aria-hidden="true">
            {[0, 1].map((i) => (
              <div key={i} className="session">
                <Skeleton w={38} h={38} style={{ borderRadius: 11 }} />
                <div style={{ flex: 1 }}>
                  <Skeleton w={140} h={13} />
                  <div style={{ height: 6 }} />
                  <Skeleton w={200} h={10} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="session-list">
            {sessions.map((s) => {
              const dev = deviceOf(s.user_agent);
              return (
                <div key={s.id} className={`session ${s.current ? "current" : ""}`}>
                  <span className="dev-icon"><Icon name={dev.icon} size={17} /></span>
                  <div className="sbody">
                    <div className="st">
                      {dev.label}
                      {s.current && <span className="chip small ok-chip">this device</span>}
                    </div>
                    <div className="sd">
                      <span className="mono">{s.ip ?? "unknown IP"}</span>
                      <span className="dim"> · </span>
                      last seen {relTime(s.last_seen_at)}
                    </div>
                  </div>
                  {!s.current && (
                    <button className="btn small ghost" onClick={() => setConfirmRevokeOne(s)}>
                      <Icon name="x" size={13} />Sign out
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <Confirm
        open={confirmRevokeAll} onClose={() => setConfirmRevokeAll(false)}
        title="Sign out everywhere else?"
        confirmLabel="Sign them out"
        onConfirm={() => {
          setConfirmRevokeAll(false);
          void act(() => api.post("/api/v1/auth/sessions/revoke-others"), "Other devices signed out.");
        }}
      >
        Every other device — phones, laptops, browsers — will need to sign in again.
        This device stays signed in.
      </Confirm>

      <Confirm
        open={!!confirmRevokeOne} onClose={() => setConfirmRevokeOne(null)}
        title="Sign out this device?"
        confirmLabel="Sign out"
        onConfirm={() => {
          const s = confirmRevokeOne;
          setConfirmRevokeOne(null);
          if (s) void act(() => api.del(`/api/v1/auth/sessions/${s.id}`), "Device signed out.");
        }}
      >
        {confirmRevokeOne && (
          <>{deviceOf(confirmRevokeOne.user_agent).label} at <span className="mono">{confirmRevokeOne.ip}</span> will need to sign in again.</>
        )}
      </Confirm>

      <Confirm
        open={confirmMfaOff} onClose={() => setConfirmMfaOff(false)}
        title="Turn off two-factor?"
        icon="shield-off"
        confirmLabel="Turn off"
        onConfirm={() => {
          setConfirmMfaOff(false);
          void act(() => api.post("/api/v1/me/mfa/disable", { password: disablePassword }), "Two-factor turned off.")
            .then(() => setDisablePassword(""));
        }}
      >
        Your account will be protected by password alone. You can turn two-factor back on at any time.
      </Confirm>
    </section>
  );
}
