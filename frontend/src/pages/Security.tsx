/** Password and active sessions — the two things a user needs when they suspect
 *  their account has been used by someone else. */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type SessionRow } from "../lib/api";
import { Alert, Badge, Empty, Field, Spinner, describeAgent, formatDate, relativeTime } from "../components/ui";

export default function Security() {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [loading, setLoading] = useState(true);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await api.mySessions();
      setSessions(result.sessions);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const mismatch = confirm.length > 0 && next !== confirm;

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.changePassword(current, next);
      setMessage(
        result.sessions_revoked > 0
          ? `Password updated. ${result.sessions_revoked} other session(s) were signed out.`
          : "Password updated.",
      );
      setCurrent("");
      setNext("");
      setConfirm("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change your password.");
    } finally {
      setBusy(false);
    }
  }

  async function endSession(id: string) {
    await api.endSession(id);
    await load();
  }

  async function endAll() {
    const result = await api.revokeAllSessions();
    setMessage(`Signed out of ${result.sessions_revoked} other session(s).`);
    await load();
  }

  return (
    <div className="content">
      <h1 className="page-title">Security</h1>
      <p className="page-sub">Your password and every device signed in to Hynt.</p>

      <form className="card" onSubmit={changePassword}>
        <h2 className="card-title">Change password</h2>
        <p className="card-sub" style={{ marginBottom: 14 }}>
          Changing your password signs you out of every other device.
        </p>

        {error ? <Alert kind="error">{error}</Alert> : null}
        {message ? <Alert kind="success">{message}</Alert> : null}

        <Field label="Current password">
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)}
                 autoComplete="current-password" required />
        </Field>
        <Field label="New password" hint="At least 10 characters.">
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)}
                 autoComplete="new-password" required minLength={10} />
        </Field>
        <Field label="Confirm new password">
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                 autoComplete="new-password" required />
        </Field>
        {mismatch ? (
          <div className="faint" style={{ color: "var(--danger)", marginTop: 6 }}>
            Passwords do not match.
          </div>
        ) : null}

        <div style={{ marginTop: 16 }}>
          <button className="btn btn-primary"
                  disabled={busy || mismatch || !current || next.length < 10}>
            {busy ? <Spinner /> : null} Update password
          </button>
        </div>
      </form>

      <div className="card">
        <div className="card-head">
          <div>
            <h2 className="card-title">Active sessions</h2>
            <p className="card-sub">Each one can open any platform without signing in again.</p>
          </div>
          {sessions.length > 1 ? (
            <button className="btn btn-danger btn-sm" onClick={() => void endAll()}>
              Sign out everywhere else
            </button>
          ) : null}
        </div>

        {loading ? (
          <Empty><Spinner /></Empty>
        ) : sessions.length === 0 ? (
          <Empty>No active sessions.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Device</th>
                  <th>IP address</th>
                  <th>Last active</th>
                  <th>Signed in</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessions.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {describeAgent(row.user_agent)}{" "}
                      {row.current ? <Badge kind="active">this device</Badge> : null}
                    </td>
                    <td className="mono">{row.ip_address ?? "—"}</td>
                    <td className="muted">{relativeTime(row.last_seen_at)}</td>
                    <td className="muted">{formatDate(row.created_at)}</td>
                    <td style={{ textAlign: "right" }}>
                      {row.current ? null : (
                        <button className="btn btn-danger btn-sm" onClick={() => void endSession(row.id)}>
                          Sign out
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
