import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { useSession } from "../lib/session";
import { Alert, Badge, Field, Spinner, formatDate } from "../components/ui";

export default function Profile() {
  const { user, setUser } = useSession();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!user) return null;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.updateMe({ full_name: fullName.trim() });
      setUser(result.user);
      setMessage("Profile updated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content">
      <h1 className="page-title">Profile</h1>
      <p className="page-sub">This is the identity every Hynt platform sees.</p>

      <form className="card" onSubmit={onSubmit}>
        <div className="card-head">
          <div>
            <h2 className="card-title">Your details</h2>
            <p className="card-sub">Your name appears in audit logs and on each platform.</p>
          </div>
          {user.is_superadmin ? <Badge kind="superadmin">superadmin</Badge> : null}
        </div>

        {error ? <Alert kind="error">{error}</Alert> : null}
        {message ? <Alert kind="success">{message}</Alert> : null}

        <Field label="Full name">
          <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </Field>

        <Field
          label="Email"
          hint="Your email is the key to every platform. Contact an administrator to change it."
        >
          <input type="email" value={user.email} disabled />
        </Field>

        <div style={{ marginTop: 16 }}>
          <button className="btn btn-primary" disabled={busy || !fullName.trim()}>
            {busy ? <Spinner /> : null} Save changes
          </button>
        </div>
      </form>

      <div className="card">
        <h2 className="card-title">Account</h2>
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <tbody>
              <tr>
                <td className="muted" style={{ width: 180 }}>Status</td>
                <td><Badge kind={user.status}>{user.status}</Badge></td>
              </tr>
              <tr>
                <td className="muted">Email verified</td>
                <td>{user.email_verified ? "Yes" : "No"}</td>
              </tr>
              <tr>
                <td className="muted">Last sign-in</td>
                <td>{formatDate(user.last_login_at)}</td>
              </tr>
              <tr>
                <td className="muted">Member since</td>
                <td>{formatDate(user.created_at)}</td>
              </tr>
              <tr>
                <td className="muted">User ID</td>
                <td className="mono">{user.id}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
