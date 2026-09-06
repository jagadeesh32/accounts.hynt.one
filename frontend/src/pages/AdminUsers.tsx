/** Superadmin: every account across the estate. */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type User } from "../lib/api";
import { useSession } from "../lib/session";
import { Alert, Badge, Empty, Field, Spinner, formatDate, relativeTime } from "../components/ui";

export default function AdminUsers() {
  const { user: me } = useSession();
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.admin.users({ q: search, offset });
      setUsers(result.users);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load users.");
    } finally {
      setLoading(false);
    }
  }, [search, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  async function setStatus(target: User, status: string) {
    setError(null);
    try {
      await api.admin.updateUser(target.id, { status });
      setNotice(
        status === "suspended"
          ? `${target.email} suspended and signed out everywhere.`
          : `${target.email} reinstated.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the account.");
    }
  }

  async function forceSignOut(target: User) {
    try {
      const result = await api.admin.revokeUserSessions(target.id);
      setNotice(`Ended ${result.sessions_revoked} session(s) for ${target.email}.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not end sessions.");
    }
  }

  return (
    <div className="content">
      <div className="row-between" style={{ marginBottom: 22 }}>
        <div>
          <h1 className="page-title">Users</h1>
          <p className="page-sub" style={{ margin: 0 }}>{total} account(s) across every platform.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setCreating((open) => !open)}>
          {creating ? "Cancel" : "New user"}
        </button>
      </div>

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      {creating ? (
        <CreateUser
          onCreated={(message) => {
            setNotice(message);
            setCreating(false);
            void load();
          }}
        />
      ) : null}

      <div className="card">
        <div className="card-head">
          <input
            type="text"
            placeholder="Search by email or name…"
            value={search}
            onChange={(e) => {
              setOffset(0);
              setSearch(e.target.value);
            }}
            style={{ maxWidth: 320 }}
          />
        </div>

        {loading ? (
          <Empty><Spinner /></Empty>
        ) : users.length === 0 ? (
          <Empty>No accounts match.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Status</th>
                  <th>Last sign-in</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link to={`/admin/users/${row.id}`} style={{ color: "inherit" }}>
                        <div style={{ fontWeight: 550 }}>{row.full_name || "—"}</div>
                        <div className="faint mono">{row.email}</div>
                      </Link>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <Badge kind={row.status}>{row.status}</Badge>
                        {row.is_superadmin ? <Badge kind="superadmin">superadmin</Badge> : null}
                      </div>
                    </td>
                    <td className="muted">{relativeTime(row.last_login_at)}</td>
                    <td className="muted">{formatDate(row.created_at)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {row.id === me?.id ? (
                        <span className="faint">you</span>
                      ) : (
                        <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          <Link className="btn btn-sm" to={`/admin/users/${row.id}`}>Manage</Link>
                          <button className="btn btn-sm" onClick={() => void forceSignOut(row)}>
                            Sign out
                          </button>
                          {row.status === "suspended" ? (
                            <button className="btn btn-sm" onClick={() => void setStatus(row, "active")}>
                              Reinstate
                            </button>
                          ) : (
                            <button className="btn btn-sm btn-danger" onClick={() => void setStatus(row, "suspended")}>
                              Suspend
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > 50 ? (
          <div className="row-between" style={{ marginTop: 14 }}>
            <button className="btn btn-sm" disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - 50))}>
              Previous
            </button>
            <span className="faint">{offset + 1}–{Math.min(offset + 50, total)} of {total}</span>
            <button className="btn btn-sm" disabled={offset + 50 >= total}
                    onClick={() => setOffset(offset + 50)}>
              Next
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CreateUser({ onCreated }: { onCreated: (message: string) => void }) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.admin.createUser({
        email: email.trim(),
        full_name: fullName.trim(),
        // No password means a PENDING account plus an activation token — the
        // invitation path, rather than an administrator inventing a password
        // and sending it over chat.
        ...(invite ? {} : { password }),
      });
      if (result.activation_token) {
        setToken(result.activation_token);
      } else {
        onCreated(`Created ${result.user.email}.`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  }

  if (token) {
    const link = `${window.location.origin}/reset-password?token=${encodeURIComponent(token)}`;
    return (
      <div className="card">
        <h2 className="card-title">Invitation created</h2>
        <Alert kind="info">
          Send this link to {email}. It expires in seven days and can be used once.
          <div className="mono" style={{ marginTop: 8, wordBreak: "break-all" }}>{link}</div>
        </Alert>
        <button className="btn" onClick={() => onCreated(`Invited ${email}.`)}>Done</button>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <h2 className="card-title">New user</h2>
      <p className="card-sub" style={{ marginBottom: 14 }}>
        The account gets the default role and plan on every platform that defines one.
      </p>

      {error ? <Alert kind="error">{error}</Alert> : null}

      <Field label="Email">
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </Field>
      <Field label="Full name">
        <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} />
      </Field>

      <div className="field">
        <label>
          <input type="checkbox" checked={invite} onChange={(e) => setInvite(e.target.checked)}
                 style={{ width: "auto", marginRight: 8 }} />
          Send an activation link instead of setting a password
        </label>
      </div>

      {invite ? null : (
        <Field label="Password" hint="At least 10 characters.">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 minLength={10} required />
        </Field>
      )}

      <div style={{ marginTop: 16 }}>
        <button className="btn btn-primary" disabled={busy || !email}>
          {busy ? <Spinner /> : null} Create account
        </button>
      </div>
    </form>
  );
}
