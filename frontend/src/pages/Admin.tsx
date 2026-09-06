import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";

interface AdminPlatform { slug: string; name: string; your_rank: number }
interface Member {
  user_id: string; email: string; full_name: string; status: string;
  role: string; rank: number; plan: string | null; plan_status: string | null;
  last_login_at: string | null;
}
interface RoleRow { slug: string; name: string; rank: number; grantable: boolean }
interface PlanRow { slug: string; name: string; price_inr: number; is_default: boolean }

/** The per-platform console. Everything here is scoped to one platform and to
 *  the caller's rank on it — a Terminal admin never sees X-Terminal. */
export function AdminPage() {
  const [platforms, setPlatforms] = useState<AdminPlatform[]>([]);
  const [slug, setSlug] = useState<string>("");
  const [members, setMembers] = useState<Member[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [q, setQ] = useState("");
  const [note, setNote] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [invite, setInvite] = useState({ email: "", role: "user", plan: "" });

  useEffect(() => {
    void api.get<{ platforms: AdminPlatform[] }>("/api/v1/admin/platforms").then((d) => {
      setPlatforms(d.platforms);
      if (d.platforms.length) setSlug(d.platforms[0].slug);
    });
  }, []);

  const load = useCallback(async () => {
    if (!slug) return;
    const [m, r, p] = await Promise.all([
      api.get<{ members: Member[] }>(`/api/v1/admin/${slug}/members?q=${encodeURIComponent(q)}`),
      api.get<{ roles: RoleRow[] }>(`/api/v1/admin/${slug}/roles`),
      api.get<{ plans: PlanRow[] }>(`/api/v1/admin/${slug}/plans`),
    ]);
    setMembers(m.members);
    setRoles(r.roles);
    setPlans(p.plans);
  }, [slug, q]);

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

  if (!platforms.length) {
    return (
      <section className="page">
        <header className="page-head"><h1>Admin</h1></header>
        <div className="card empty">You do not administer any platform.</div>
      </section>
    );
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Admin</h1>
        <div className="tabs">
          {platforms.map((p) => (
            <button key={p.slug} className={`tab ${p.slug === slug ? "on" : ""}`} onClick={() => setSlug(p.slug)}>
              {p.name}
            </button>
          ))}
        </div>
      </header>

      {note && <div className={`alert ${note.kind === "ok" ? "ok" : "error"}`}>{note.text}</div>}

      <div className="card">
        <h2>Invite someone</h2>
        <p className="muted">
          There is no mail on this box: a new account's temporary password is shown once, here.
        </p>
        <form className="row" onSubmit={(e) => {
          e.preventDefault();
          void act(async () => {
            const result = await api.post<{ created: boolean; temp_password: string | null }>(
              `/api/v1/admin/${slug}/invite`,
              { email: invite.email, platform: slug, role: invite.role, plan: invite.plan || null },
            );
            if (result.temp_password) {
              setNote({ kind: "ok", text: `Created ${invite.email}. Temporary password: ${result.temp_password}` });
            }
            setInvite({ email: "", role: "user", plan: "" });
          }, `${invite.email} now has access.`);
        }}>
          <input type="email" placeholder="person@example.com" required value={invite.email}
                 onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
          <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
            {roles.filter((r) => r.grantable).map((r) => <option key={r.slug} value={r.slug}>{r.name}</option>)}
          </select>
          <select value={invite.plan} onChange={(e) => setInvite({ ...invite, plan: e.target.value })}>
            <option value="">Default plan</option>
            {plans.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
          </select>
          <button className="btn primary" type="submit">Add</button>
        </form>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Members</h2>
          <input className="search" placeholder="Search name or email" value={q}
                 onChange={(e) => setQ(e.target.value)} />
        </div>
        <table className="table">
          <thead>
            <tr><th>Person</th><th>Role</th><th>Plan</th><th>Last seen</th><th /></tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id} className={m.status === "active" ? "" : "dim"}>
                <td>
                  <div className="who-text">
                    <span>{m.full_name || m.email}</span>
                    <span className="who-email">{m.email}</span>
                  </div>
                </td>
                <td>
                  <select
                    value={m.role}
                    onChange={(e) => void act(
                      () => api.patch(`/api/v1/admin/${slug}/members/${m.user_id}/role`, { role: e.target.value }),
                      `${m.email} is now ${e.target.value}.`,
                    )}
                  >
                    {roles.map((r) => (
                      <option key={r.slug} value={r.slug} disabled={!r.grantable && r.slug !== m.role}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    value={m.plan ?? ""}
                    onChange={(e) => void act(
                      () => api.post(`/api/v1/admin/${slug}/subscriptions`, {
                        email: m.email, platform: slug, plan: e.target.value, status: "active",
                      }),
                      `${m.email} moved to ${e.target.value}.`,
                    )}
                  >
                    {plans.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
                  </select>
                </td>
                <td className="muted">{m.last_login_at ? new Date(m.last_login_at).toLocaleDateString() : "never"}</td>
                <td className="right">
                  <button className="btn small danger" onClick={() => void act(
                    () => api.del(`/api/v1/admin/${slug}/members/${m.user_id}`),
                    `${m.email} removed from ${slug}.`,
                  )}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
