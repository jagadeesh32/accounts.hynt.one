import { useEffect, useState } from "react";
import { api, ApiError, type Me, type SessionRow } from "../api";

export function SecurityPage({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [note, setNote] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [mfaSetup, setMfaSetup] = useState<{ secret: string } | null>(null);
  const [otp, setOtp] = useState("");
  const [disablePassword, setDisablePassword] = useState("");

  const loadSessions = () =>
    api.get<{ sessions: SessionRow[] }>("/api/v1/auth/sessions").then((d) => setSessions(d.sessions));

  useEffect(() => {
    void loadSessions();
  }, []);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setNote(null);
    try {
      await fn();
      setNote({ kind: "ok", text: ok });
      await loadSessions();
      onChanged();
    } catch (err) {
      setNote({ kind: "error", text: err instanceof ApiError ? err.message : "Something went wrong." });
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Security</h1>
        <p className="muted">Your password, two-factor and signed-in devices.</p>
      </header>

      {note && <div className={`alert ${note.kind === "ok" ? "ok" : "error"}`}>{note.text}</div>}

      <div className="card">
        <h2>Password</h2>
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
          <input type="password" placeholder="Current password" value={current} required
                 autoComplete="current-password" onChange={(e) => setCurrent(e.target.value)} />
          <input type="password" placeholder="New password (10+ characters)" value={next} required
                 minLength={10} autoComplete="new-password" onChange={(e) => setNext(e.target.value)} />
          <button className="btn primary" type="submit">Change</button>
        </form>
      </div>

      <div className="card">
        <h2>Two-factor authentication</h2>
        {me.mfa_enabled ? (
          <>
            <p className="ok-text">Two-factor is on.</p>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post("/api/v1/me/mfa/disable", { password: disablePassword }), "Two-factor turned off.")
                .then(() => setDisablePassword(""));
            }}>
              <input type="password" placeholder="Confirm your password" value={disablePassword} required
                     onChange={(e) => setDisablePassword(e.target.value)} />
              <button className="btn danger" type="submit">Turn off</button>
            </form>
          </>
        ) : mfaSetup ? (
          <>
            <p className="muted">Scan this with your authenticator app, then enter the code it shows.</p>
            <div className="mfa">
              <img className="qr" src="/api/v1/me/mfa/qr.png" alt="Two-factor QR code" />
              <div>
                <p className="muted">Or enter this key by hand:</p>
                <code className="secret">{mfaSetup.secret}</code>
              </div>
            </div>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post("/api/v1/me/mfa/enable", { otp }), "Two-factor is on.")
                .then(() => { setMfaSetup(null); setOtp(""); });
            }}>
              <input inputMode="numeric" maxLength={6} placeholder="123456" value={otp} required
                     onChange={(e) => setOtp(e.target.value)} />
              <button className="btn primary" type="submit">Turn on</button>
            </form>
          </>
        ) : (
          <>
            <p className="muted">Add a second step when signing in.</p>
            <button className="btn" onClick={() => {
              void api.post<{ secret: string }>("/api/v1/me/mfa/setup").then(setMfaSetup);
            }}>Set up two-factor</button>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Signed-in devices</h2>
          <button className="btn ghost" onClick={() => void act(
            () => api.post("/api/v1/auth/sessions/revoke-others"), "Other devices signed out.",
          )}>Sign out everywhere else</button>
        </div>
        <table className="table">
          <thead>
            <tr><th>Device</th><th>IP</th><th>Last seen</th><th /></tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id}>
                <td>
                  {shortenAgent(s.user_agent)}
                  {s.current && <span className="chip small">this device</span>}
                </td>
                <td className="mono">{s.ip}</td>
                <td>{new Date(s.last_seen_at).toLocaleString()}</td>
                <td className="right">
                  {!s.current && (
                    <button className="btn small danger" onClick={() => void act(
                      () => api.del(`/api/v1/auth/sessions/${s.id}`), "Device signed out.",
                    )}>Sign out</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** User agents are long and mostly noise; show the part a person recognises. */
function shortenAgent(agent: string | null): string {
  if (!agent) return "Unknown device";
  const browser = /Edg\//.test(agent) ? "Edge"
    : /Chrome\//.test(agent) ? "Chrome"
    : /Safari\//.test(agent) ? "Safari"
    : /Firefox\//.test(agent) ? "Firefox"
    : "Browser";
  const os = /Windows/.test(agent) ? "Windows"
    : /Mac OS X/.test(agent) ? "macOS"
    : /Android/.test(agent) ? "Android"
    : /iPhone|iPad/.test(agent) ? "iOS"
    : /Linux/.test(agent) ? "Linux"
    : "";
  return os ? `${browser} on ${os}` : browser;
}
