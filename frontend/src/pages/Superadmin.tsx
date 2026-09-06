import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";

interface Stats { users: number; suspended: number; active_sessions: number; platforms: number; memberships: number; clients: number }
interface UserRow {
  id: string; email: string; full_name: string; status: string; is_superadmin: boolean;
  mfa_enabled: boolean; last_login_at: string | null;
  memberships: { platform: string; role: string }[];
}
interface KeyRow { kid: string; is_active: boolean; created_at: string; retired_at: string | null }
interface ClientRow { client_id: string; name: string; platform: string; redirect_uris: string[]; is_active: boolean }
interface AuditRow { at: string; action: string; actor: string | null; target: string | null; ip: string | null }

type Tab = "users" | "clients" | "keys" | "audit";

/** Running the identity provider itself. */
export function SuperadminPage() {
  const [tab, setTab] = useState<Tab>("users");
  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [q, setQ] = useState("");
  const [note, setNote] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const [s, u] = await Promise.all([
      api.get<Stats>("/api/v1/superadmin/stats"),
      api.get<{ users: UserRow[] }>(`/api/v1/superadmin/users?q=${encodeURIComponent(q)}`),
    ]);
    setStats(s);
    setUsers(u.users);
    if (tab === "clients") setClients((await api.get<{ clients: ClientRow[] }>("/api/v1/superadmin/clients")).clients);
    if (tab === "keys") setKeys((await api.get<{ keys: KeyRow[] }>("/api/v1/superadmin/keys")).keys);
    if (tab === "audit") setAudit((await api.get<{ events: AuditRow[] }>("/api/v1/superadmin/audit")).events);
  }, [q, tab]);

  useEffect(() => { void load(); }, [load]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setNote(null);
    try {
      await fn();
      setNote({ kind: "ok", text: ok });
      await load();
    } catch (err) {
      setNote({ kind: "error", text: err instanceof ApiError ? err.message : "Something went wrong." });
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Estate</h1>
        <p className="muted">The identity provider itself.</p>
      </header>

      {stats && (
        <div className="stats">
          <Stat label="Accounts" value={stats.users} />
          <Stat label="Suspended" value={stats.suspended} warn={stats.suspended > 0} />
          <Stat label="Live sessions" value={stats.active_sessions} />
          <Stat label="Platforms" value={stats.platforms} />
          <Stat label="Memberships" value={stats.memberships} />
          <Stat label="Clients" value={stats.clients} />
        </div>
      )}

      {note && <div className={`alert ${note.kind === "ok" ? "ok" : "error"}`}>{note.text}</div>}

      <div className="tabs">
        {(["users", "clients", "keys", "audit"] as Tab[]).map((t) => (
          <button key={t} className={`tab ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "users" && (
        <div className="card">
          <div className="card-head">
            <h2>Accounts</h2>
            <input className="search" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <table className="table">
            <thead>
              <tr><th>Person</th><th>Access</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.status === "active" ? "" : "dim"}>
                  <td>
                    <div className="who-text">
                      <span>{u.full_name || u.email}{u.is_superadmin && <span className="chip small">superadmin</span>}</span>
                      <span className="who-email">{u.email}</span>
                    </div>
                  </td>
                  <td>
                    <div className="chips">
                      {u.memberships.map((m) => (
                        <span key={m.platform} className="chip">{m.platform}:{m.role}</span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <span className={`chip ${u.status === "active" ? "ok-chip" : "warn"}`}>{u.status}</span>
                    {u.mfa_enabled && <span className="chip small">2FA</span>}
                  </td>
                  <td className="right">
                    {u.status === "active" ? (
                      <button className="btn small danger" onClick={() => void act(
                        () => api.post(`/api/v1/superadmin/users/${u.id}/suspend`),
                        `${u.email} suspended — every platform stops honouring their tokens within seconds.`,
                      )}>Suspend</button>
                    ) : (
                      <button className="btn small" onClick={() => void act(
                        () => api.post(`/api/v1/superadmin/users/${u.id}/reinstate`), `${u.email} reinstated.`,
                      )}>Reinstate</button>
                    )}
                    <button className="btn small ghost" onClick={() => void act(async () => {
                      const r = await api.post<{ password: string | null }>(`/api/v1/superadmin/users/${u.id}/password`);
                      setNote({ kind: "ok", text: `New password for ${u.email}: ${r.password}` });
                    }, "Password reset.")}>Reset password</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "clients" && (
        <div className="card">
          <h2>OAuth clients</h2>
          <p className="muted">One public, PKCE-only client per platform SPA.</p>
          <table className="table">
            <thead><tr><th>Client</th><th>Platform</th><th>Redirect URIs</th></tr></thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.client_id}>
                  <td><span className="mono">{c.client_id}</span><div className="who-email">{c.name}</div></td>
                  <td>{c.platform}</td>
                  <td className="mono small-text">{c.redirect_uris.join("\n")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "keys" && (
        <div className="card">
          <div className="card-head">
            <h2>Signing keys</h2>
            <button className="btn" onClick={() => void act(
              () => api.post("/api/v1/superadmin/keys/rotate"),
              "Rotated. Platforms pick the new key up on their next JWKS refresh (up to an hour).",
            )}>Rotate</button>
          </div>
          <p className="muted">
            A retired key stays published until the last token it signed has expired — rotating
            never signs anyone out.
          </p>
          <table className="table">
            <thead><tr><th>Key id</th><th>State</th><th>Created</th></tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.kid}>
                  <td className="mono">{k.kid}</td>
                  <td><span className={`chip ${k.is_active ? "ok-chip" : ""}`}>{k.is_active ? "active" : "retired"}</span></td>
                  <td className="muted">{new Date(k.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "audit" && (
        <div className="card">
          <h2>Audit</h2>
          <table className="table">
            <thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Target</th><th>IP</th></tr></thead>
            <tbody>
              {audit.map((e, i) => (
                <tr key={i}>
                  <td className="muted">{new Date(e.at).toLocaleString()}</td>
                  <td className="mono">{e.action}</td>
                  <td>{e.actor ?? "—"}</td>
                  <td className="muted">{e.target ?? "—"}</td>
                  <td className="mono muted">{e.ip ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Stat({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className={`stat ${warn ? "warn" : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
