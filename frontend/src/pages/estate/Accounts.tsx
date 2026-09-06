import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { NoteBanner, useNote } from "../../lib/useNote";
import { Drawer, Field } from "../../widgets/Drawer";

interface UserRow {
  id: string; email: string; full_name: string; status: string; is_superadmin: boolean;
  mfa_enabled: boolean; last_login_at: string | null;
  memberships: { platform: string; role: string }[];
}
interface PlatformRow { slug: string; name: string }
interface NewUser { email: string; full_name: string; password: string; platform: string; role: string }

const EMPTY: NewUser = { email: "", full_name: "", password: "", platform: "", role: "user" };

export function AccountsPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [platforms, setPlatforms] = useState<PlatformRow[]>([]);
  const [q, setQ] = useState("");
  const [draft, setDraft] = useState<NewUser | null>(null);
  const [saving, setSaving] = useState(false);
  const { note, setNote, act } = useNote();

  const load = useCallback(async () => {
    const [u, p] = await Promise.all([
      api.get<{ users: UserRow[] }>(`/api/v1/superadmin/users?q=${encodeURIComponent(q)}`),
      api.get<{ platforms: PlatformRow[] }>("/api/v1/superadmin/platforms"),
    ]);
    setUsers(u.users);
    setPlatforms(p.platforms);
  }, [q]);

  useEffect(() => { void load(); }, [load]);

  async function create() {
    if (!draft) return;
    setSaving(true);
    setNote(null);
    const ok = await act(async () => {
      const r = await api.post<{ password: string | null }>("/api/v1/superadmin/users", {
        email: draft.email,
        full_name: draft.full_name || null,
        password: draft.password || null,
        platform: draft.platform || null,
        role: draft.role,
      });
      // A generated password is shown exactly once and is never recoverable, so
      // it has to outlive the drawer closing.
      setNote(r.password
        ? { kind: "ok", text: `Created ${draft.email}. Temporary password: ${r.password}` }
        : { kind: "ok", text: `Created ${draft.email}.` });
    }, `Created ${draft.email}.`, load);
    if (ok) setDraft(null);
    setSaving(false);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Accounts</h1>
        <p className="muted">Every account in the estate, and what it can reach.</p>
      </header>

      <NoteBanner note={note} />

      <div className="card">
        <div className="card-head">
          <h2>{users.length} account{users.length === 1 ? "" : "s"}</h2>
          <div className="filters">
            <input className="search" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="btn primary" onClick={() => setDraft({ ...EMPTY })}>New account</button>
          </div>
        </div>
        <table className="table">
          <thead><tr><th>Person</th><th>Access</th><th>Status</th><th /></tr></thead>
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
                    {u.memberships.map((m) => <span key={m.platform} className="chip">{m.platform}:{m.role}</span>)}
                    {!u.memberships.length && <span className="muted">no platforms</span>}
                  </div>
                </td>
                <td>
                  <span className={`chip ${u.status === "active" ? "ok-chip" : "warn"}`}>{u.status}</span>
                  {u.mfa_enabled && <span className="chip small">2FA</span>}
                </td>
                <td className="right">
                  {u.status === "active" ? (
                    <button className="btn small danger" onClick={() => {
                      if (!window.confirm(`Suspend ${u.email}? Every platform stops honouring their tokens within seconds.`)) return;
                      void act(() => api.post(`/api/v1/superadmin/users/${u.id}/suspend`),
                        `${u.email} suspended — tokens revoked estate-wide within seconds.`, load);
                    }}>Suspend</button>
                  ) : (
                    <button className="btn small" onClick={() => void act(
                      () => api.post(`/api/v1/superadmin/users/${u.id}/reinstate`), `${u.email} reinstated.`, load,
                    )}>Reinstate</button>
                  )}
                  <button className="btn small ghost" onClick={() => void act(async () => {
                    const r = await api.post<{ password: string | null }>(`/api/v1/superadmin/users/${u.id}/password`);
                    setNote({ kind: "ok", text: `New password for ${u.email}: ${r.password}` });
                  }, "Password reset.", load)}>Reset password</button>
                  <button
                    className={`btn small ${u.is_superadmin ? "danger" : "ghost"}`}
                    onClick={() => {
                      const enabling = !u.is_superadmin;
                      if (!window.confirm(enabling
                        ? `Give ${u.email} superadmin? They will be able to administer every platform, every account and the signing keys.`
                        : `Remove superadmin from ${u.email}?`)) return;
                      void act(
                        () => api.post(`/api/v1/superadmin/users/${u.id}/superadmin`, { enabled: enabling }),
                        `${u.email} ${enabling ? "is now a superadmin" : "is no longer a superadmin"}. Their tokens are revoked estate-wide within seconds.`,
                        load,
                      );
                    }}
                  >
                    {u.is_superadmin ? "Revoke superadmin" : "Make superadmin"}
                  </button>
                </td>
              </tr>
            ))}
            {!users.length && <tr><td colSpan={4} className="muted">No accounts match that search.</td></tr>}
          </tbody>
        </table>
      </div>

      <Drawer
        open={draft !== null}
        title="New account"
        subtitle="Creates the account directly — no invitation is sent."
        onClose={() => setDraft(null)}
        onSave={() => void create()}
        busy={saving || !draft?.email}
        saveLabel="Create account"
      >
        {draft && (
          <>
            <Field label="Email">
              <input type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
            </Field>
            <Field label="Full name" hint="Optional">
              <input value={draft.full_name} onChange={(e) => setDraft({ ...draft, full_name: e.target.value })} />
            </Field>
            <Field label="Password" hint="Leave blank to generate one and show it once">
              <input value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
            </Field>
            <div className="dw-row">
              <Field label="Grant access to" hint="Optional">
                <select value={draft.platform} onChange={(e) => setDraft({ ...draft, platform: e.target.value })}>
                  <option value="">No platform yet</option>
                  {platforms.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
                </select>
              </Field>
              <Field label="Role" hint="Slug, e.g. user or admin">
                <input value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} />
              </Field>
            </div>
          </>
        )}
      </Drawer>
    </section>
  );
}
