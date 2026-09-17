import { useEffect, useState } from "react";
import { api, ApiError, type Me, type SessionRow } from "../api";
import { DataTable } from "../widgets/DataTable";

export function SecurityPage({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [note, setNote] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [mfaSetup, setMfaSetup] = useState<{ secret: string } | null>(null);
  const [otp, setOtp] = useState("");
  const [disablePassword, setDisablePassword] = useState("");
  const [regenPassword, setRegenPassword] = useState("");
  // Shown once, right after enable or regenerate; gone on the next render of
  // anything else. The server keeps only hashes, so there is no "show again".
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [fullName, setFullName] = useState(me.full_name ?? "");

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
        <h2>Profile</h2>
        <p className="muted">
          Your name travels in the token's <span className="mono">name</span> claim, so every desk
          shows the new one on its next token — within 15 minutes.
        </p>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            void act(() => api.patch("/api/v1/me", { full_name: fullName.trim() || null }), "Profile saved.");
          }}
        >
          <input
            value={fullName}
            placeholder="Your name"
            maxLength={200}
            onChange={(e) => setFullName(e.target.value)}
          />
          <button className="btn primary" type="submit" disabled={fullName.trim() === (me.full_name ?? "").trim()}>
            Save
          </button>
        </form>
        <p className="fineprint">Signed in as <span className="mono">{me.email}</span>.</p>
      </div>

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
        {recoveryCodes && (
          <RecoveryCodes codes={recoveryCodes} onDone={() => setRecoveryCodes(null)} />
        )}
        {me.mfa_enabled ? (
          <>
            <p className="ok-text">Two-factor is on.</p>
            <p className="muted">
              {me.recovery_codes_remaining === 0
                ? "You have no recovery codes left — generate a new set now, or a lost phone means a locked account."
                : `${me.recovery_codes_remaining} of 10 recovery codes unused. Each signs you in once if your phone is unavailable.`}
            </p>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                const r = await api.post<{ recovery_codes: string[] }>("/api/v1/me/mfa/recovery-codes", { password: regenPassword });
                setRecoveryCodes(r.recovery_codes);
              }, "New recovery codes issued. The old ones no longer work.")
                .then(() => setRegenPassword(""));
            }}>
              <input type="password" placeholder="Confirm your password" value={regenPassword} required
                     autoComplete="current-password" onChange={(e) => setRegenPassword(e.target.value)} />
              <button className="btn" type="submit">New recovery codes</button>
            </form>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post("/api/v1/me/mfa/disable", { password: disablePassword }), "Two-factor turned off.")
                .then(() => { setDisablePassword(""); setRecoveryCodes(null); });
            }}>
              <input type="password" placeholder="Confirm your password" value={disablePassword} required
                     autoComplete="current-password" onChange={(e) => setDisablePassword(e.target.value)} />
              <button className="btn danger" type="submit">Turn off</button>
            </form>
          </>
        ) : mfaSetup ? (
          <>
            <p className="muted">
              Scan this with your authenticator app (Google Authenticator, Authy, 1Password, Microsoft
              Authenticator…), then enter the code it shows.
            </p>
            <div className="mfa">
              <img className="qr" src="/api/v1/me/mfa/qr.png" alt="Two-factor QR code" />
              <div>
                <p className="muted">Or enter this key by hand:</p>
                <code className="secret">{mfaSetup.secret}</code>
              </div>
            </div>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                const r = await api.post<{ recovery_codes: string[] }>("/api/v1/me/mfa/enable", { otp });
                setRecoveryCodes(r.recovery_codes);
              }, "Two-factor is on. Save your recovery codes before leaving this page.")
                .then(() => { setMfaSetup(null); setOtp(""); });
            }}>
              <input className="otp-input" inputMode="numeric" maxLength={6} placeholder="123456" value={otp} required
                     autoComplete="one-time-code" onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />
              <button className="btn primary" type="submit">Turn on</button>
            </form>
          </>
        ) : (
          <>
            <p className="muted">Add a second step when signing in: a six-digit code from an authenticator app on your phone.</p>
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
        <DataTable
          id="my-sessions"
          rows={sessions}
          getKey={(s) => s.id}
          initialSort="seen"
          dense
          searchPlaceholder="Search device or IP"
          columns={[
            {
              key: "device", header: "Device", value: (s) => shortenAgent(s.user_agent),
              render: (s) => (
                <>
                  {shortenAgent(s.user_agent)}
                  {s.current && <span className="chip small">this device</span>}
                </>
              ),
            },
            { key: "ip", header: "IP", value: (s) => s.ip ?? "", className: "mono" },
            {
              key: "seen", header: "Last seen", value: (s) => s.last_seen_at,
              render: (s) => new Date(s.last_seen_at).toLocaleString(),
            },
            {
              key: "out", header: "", align: "right",
              render: (s) => (
                !s.current && (
                  <button className="btn small danger" onClick={() => void act(
                    () => api.del(`/api/v1/auth/sessions/${s.id}`), "Device signed out.",
                  )}>Sign out</button>
                )
              ),
            },
          ]}
        />
      </div>
    </section>
  );
}

/** The one-time reveal of recovery codes, with copy and print — there is no
 *  second look, so the exits are deliberate. */
function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n");
  return (
    <div className="recovery">
      <p><strong>Save these recovery codes now.</strong> They are shown only once. Each one signs you in a single
        time if you lose your phone — keep them somewhere that is not the phone.</p>
      <ol className="recovery-codes">
        {codes.map((c) => <li key={c}><code>{c}</code></li>)}
      </ol>
      <div className="row">
        <button className="btn" type="button" onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => setCopied(true));
        }}>{copied ? "Copied" : "Copy"}</button>
        <button className="btn" type="button" onClick={() => window.print()}>Print</button>
        <button className="btn ghost" type="button" onClick={() => {
          if (window.confirm("Have you saved the codes? They cannot be shown again.")) onDone();
        }}>I've saved them</button>
      </div>
    </div>
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
