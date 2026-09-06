import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import {
  Avatar, Confirm, CopyButton, Empty, Icon, Segmented, Skeleton, relTime, useToast,
} from "../ui";

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
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("users");
  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [keys, setKeys] = useState<KeyRow[] | null>(null);
  const [audit, setAudit] = useState<AuditRow[] | null>(null);
  const [q, setQ] = useState("");
  const [suspending, setSuspending] = useState<UserRow | null>(null);
  const [rotating, setRotating] = useState(false);
  const [resetSecret, setResetSecret] = useState<{ email: string; password: string } | null>(null);

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

  async function act(fn: () => Promise<unknown>, ok: string, desc?: string) {
    try {
      await fn();
      toast.ok(ok, desc);
      await load();
    } catch (err) {
      toast.error("Something went wrong", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Estate</h1>
        <p className="sub">The identity provider itself — every account, client and key in the fleet.</p>
      </header>

      {stats ? (
        <div className="stats">
          <Stat icon="users" label="Accounts" value={stats.users} />
          <Stat icon="ban" label="Suspended" value={stats.suspended} tone={stats.suspended > 0 ? "warn" : undefined} />
          <Stat icon="activity" label="Live sessions" value={stats.active_sessions} tone="cyan" />
          <Stat icon="layers" label="Platforms" value={stats.platforms} />
          <Stat icon="link" label="Memberships" value={stats.memberships} />
          <Stat icon="server" label="Clients" value={stats.clients} tone="cyan" />
        </div>
      ) : (
        <div className="stats" aria-hidden="true">
          {[...Array(6)].map((_, i) => <div key={i} className="stat" style={{ height: 92 }} />)}
        </div>
      )}

      {resetSecret && (
        <div className="alert ok">
          <Icon name="key" size={15} />
          <div style={{ flex: 1 }}>
            New password for <b>{resetSecret.email}</b>:
            <div className="secret-reveal">
              <code>{resetSecret.password}</code>
              <CopyButton value={resetSecret.password} label="Copy password" />
              <span className="label">shown once — copy it now</span>
            </div>
          </div>
          <button className="btn ghost icon" onClick={() => setResetSecret(null)} aria-label="Dismiss">
            <Icon name="x" size={14} />
          </button>
        </div>
      )}

      <div style={{ marginBottom: 16 }}>
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: "users", label: "Users", icon: "users" },
            { value: "clients", label: "Clients", icon: "server" },
            { value: "keys", label: "Keys", icon: "hash" },
            { value: "audit", label: "Audit", icon: "history" },
          ]}
        />
      </div>

      {tab === "users" && (
        <div className="card">
          <div className="card-head">
            <h2>Accounts</h2>
            <span className="search-wrap">
              <span className="lead-icon"><Icon name="search" size={14} /></span>
              <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
            </span>
          </div>
          {!users ? (
            <div aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton-row">
                  <Skeleton w={32} h={32} style={{ borderRadius: "50%" }} />
                  <div style={{ flex: 1 }}>
                    <Skeleton w={140} h={12} />
                    <div style={{ height: 6 }} />
                    <Skeleton w={210} h={10} />
                  </div>
                </div>
              ))}
            </div>
          ) : users.length === 0 ? (
            <Empty icon="search" title="Nobody matches" hint={q ? `No account matches “${q}”.` : undefined} />
          ) : (
            <table className="table">
              <thead>
                <tr><th>Person</th><th>Access</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className={u.status === "active" ? "" : "dim"}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                        <Avatar name={u.full_name} email={u.email} size="sm" />
                        <div className="who-text">
                          <span className="who-name">
                            {u.full_name || u.email}
                            {u.is_superadmin && <span className="chip small accent-chip">superadmin</span>}
                          </span>
                          <span className="who-email">
                            {u.email} · seen {relTime(u.last_login_at)}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="chips">
                        {u.memberships.map((m) => (
                          <span key={m.platform} className="chip mono">{m.platform}:{m.role}</span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <div className="chips">
                        <span className={`chip ${u.status === "active" ? "ok-chip" : "warn"}`}>
                          <span className="dot" />{u.status}
                        </span>
                        {u.mfa_enabled && <span className="chip small accent-chip">2FA</span>}
                      </div>
                    </td>
                    <td className="right nowrap">
                      {u.status === "active" ? (
                        <button className="btn small ghost" style={{ color: "var(--danger)" }} onClick={() => setSuspending(u)}>
                          <Icon name="ban" size={13} />Suspend
                        </button>
                      ) : (
                        <button className="btn small ghost" onClick={() => void act(
                          () => api.post(`/api/v1/superadmin/users/${u.id}/reinstate`), `${u.email} reinstated.`,
                        )}>
                          <Icon name="refresh" size={13} />Reinstate
                        </button>
                      )}
                      <button className="btn small ghost" onClick={() => void act(async () => {
                        const r = await api.post<{ password: string | null }>(`/api/v1/superadmin/users/${u.id}/password`);
                        if (r.password) setResetSecret({ email: u.email, password: r.password });
                      }, "Password reset.")}>
                        <Icon name="key" size={13} />Reset password
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "clients" && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">
              <span className="ticon"><Icon name="server" size={16} /></span>
              <h2>OAuth clients</h2>
            </div>
          </div>
          <p className="muted">One public, PKCE-only client per platform SPA.</p>
          <table className="table">
            <thead><tr><th>Client</th><th>Platform</th><th>Redirect URIs</th></tr></thead>
            <tbody>
              {(clients ?? []).map((c) => (
                <tr key={c.client_id}>
                  <td>
                    <span className="mono">{c.client_id}</span>
                    <div className="who-email">{c.name}</div>
                  </td>
                  <td><span className="chip role">{c.platform}</span></td>
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
            <div className="card-title">
              <span className="ticon"><Icon name="hash" size={16} /></span>
              <h2>Signing keys</h2>
            </div>
            <button className="btn" onClick={() => setRotating(true)} disabled={rotating}>
              <Icon name="refresh" size={14} />Rotate
            </button>
          </div>
          <p className="muted">
            A retired key stays published until the last token it signed has expired — rotating
            never signs anyone out.
          </p>
          <table className="table">
            <thead><tr><th>Key id</th><th>State</th><th>Created</th></tr></thead>
            <tbody>
              {(keys ?? []).map((k) => (
                <tr key={k.kid}>
                  <td className="mono">{k.kid}</td>
                  <td>
                    <span className={`chip ${k.is_active ? "ok-chip" : ""}`}>
                      <span className="dot" />{k.is_active ? "active" : "retired"}
                    </span>
                  </td>
                  <td className="muted">{new Date(k.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "audit" && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">
              <span className="ticon"><Icon name="history" size={16} /></span>
              <h2>Audit log</h2>
            </div>
          </div>
          <table className="table">
            <thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Target</th><th>IP</th></tr></thead>
            <tbody>
              {(audit ?? []).map((e, i) => (
                <tr key={i}>
                  <td className="muted nowrap">{relTime(e.at)}</td>
                  <td><span className="audit-action">{e.action}</span></td>
                  <td>{e.actor ?? "—"}</td>
                  <td className="muted">{e.target ?? "—"}</td>
                  <td className="mono muted">{e.ip ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Confirm
        open={!!suspending} onClose={() => setSuspending(null)}
        title={`Suspend ${suspending?.email ?? ""}?`}
        confirmLabel="Suspend"
        onConfirm={() => {
          const u = suspending;
          setSuspending(null);
          if (u) void act(
            () => api.post(`/api/v1/superadmin/users/${u.id}/suspend`),
            `${u.email} suspended.`,
            "Every platform stops honouring their tokens within seconds.",
          );
        }}
      >
        Their sessions die and every platform stops honouring their tokens within seconds. They keep their
        data and can be reinstated at any time.
      </Confirm>

      <Confirm
        open={rotating} onClose={() => setRotating(false)}
        title="Rotate the signing key?"
        icon="refresh" tone="info"
        confirmLabel="Rotate now"
        onConfirm={() => {
          setRotating(false);
          void act(
            () => api.post("/api/v1/superadmin/keys/rotate"),
            "Signing key rotated.",
            "Platforms pick the new key up on their next JWKS refresh (up to an hour).",
          );
        }}
      >
        A fresh key starts signing tokens immediately. Nobody is signed out — the retired key stays
        published until the last token it signed expires.
      </Confirm>
    </section>
  );
}

function Stat({ icon, label, value, tone }: { icon: Parameters<typeof Icon>[0]["name"]; label: string; value: number; tone?: "warn" | "cyan" }) {
  return (
    <div className={`stat ${tone === "warn" ? "warn" : ""}`}>
      <span className={`sicon ${tone ?? ""}`}><Icon name={icon} size={15} /></span>
      <div className="stat-value">{value.toLocaleString()}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
