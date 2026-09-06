import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Avatar, Confirm, CopyButton, Empty, Icon, Segmented, Skeleton, relTime, useToast } from "../ui";

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
  const toast = useToast();
  const [platforms, setPlatforms] = useState<AdminPlatform[]>([]);
  const [slug, setSlug] = useState<string>("");
  const [members, setMembers] = useState<Member[] | null>(null);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [q, setQ] = useState("");
  const [invite, setInvite] = useState({ email: "", role: "user", plan: "" });
  const [busyInvite, setBusyInvite] = useState(false);
  const [tempSecret, setTempSecret] = useState<{ email: string; password: string } | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);

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
    try {
      await fn();
      toast.ok(ok);
      await load();
    } catch (err) {
      toast.error("Something went wrong", err instanceof ApiError ? err.message : undefined);
    }
  }

  if (!platforms.length) {
    return (
      <section className="page">
        <header className="page-head"><h1>Admin</h1></header>
        <div className="card">
          <Empty icon="users" title="You do not administer any platform" hint="If this is a mistake, ask the estate superadmin for an admin role." />
        </div>
      </section>
    );
  }

  const active = platforms.find((p) => p.slug === slug);

  return (
    <section className="page">
      <header className="page-head">
        <div className="headline">
          <div>
            <h1>Admin</h1>
            <p className="sub">Members, roles and plans — scoped to {active?.name ?? "your platform"} and your rank on it.</p>
          </div>
          <Segmented
            value={slug}
            onChange={setSlug}
            options={platforms.map((p) => ({ value: p.slug, label: p.name }))}
          />
        </div>
      </header>

      {tempSecret && (
        <div className="alert ok">
          <Icon name="user-plus" size={15} />
          <div style={{ flex: 1 }}>
            <b>{tempSecret.email}</b> now has access. Their temporary password:
            <div className="secret-reveal">
              <code>{tempSecret.password}</code>
              <CopyButton value={tempSecret.password} label="Copy password" />
              <span className="label">shown once — copy it now</span>
            </div>
          </div>
          <button className="tx btn ghost icon" onClick={() => setTempSecret(null)} aria-label="Dismiss">
            <Icon name="x" size={14} />
          </button>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            <span className="ticon"><Icon name="user-plus" size={16} /></span>
            <h2>Invite someone</h2>
          </div>
        </div>
        <p className="muted">
          There is no mail on this box: a new account's temporary password is shown once, here.
        </p>
        <form className="row" onSubmit={async (e) => {
          e.preventDefault();
          setBusyInvite(true);
          try {
            const result = await api.post<{ created: boolean; temp_password: string | null }>(
              `/api/v1/admin/${slug}/invite`,
              { email: invite.email, platform: slug, role: invite.role, plan: invite.plan || null },
            );
            toast.ok(`${invite.email} now has access.`);
            if (result.temp_password) {
              setTempSecret({ email: invite.email, password: result.temp_password });
            }
            setInvite({ email: "", role: "user", plan: "" });
          } catch (err) {
            toast.error("Could not invite", err instanceof ApiError ? err.message : undefined);
          } finally {
            setBusyInvite(false);
            await load();
          }
        }}>
          <span className="input-wrap" style={{ flex: "2 1 220px" }}>
            <span className="lead-icon"><Icon name="mail" size={15} /></span>
            <input
              type="email" placeholder="person@example.com" required value={invite.email}
              onChange={(e) => setInvite({ ...invite, email: e.target.value })}
            />
          </span>
          <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
            {roles.filter((r) => r.grantable).map((r) => <option key={r.slug} value={r.slug}>{r.name}</option>)}
          </select>
          <select value={invite.plan} onChange={(e) => setInvite({ ...invite, plan: e.target.value })}>
            <option value="">Default plan</option>
            {plans.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
          </select>
          <button className="btn primary" type="submit" disabled={busyInvite}>
            {busyInvite ? "Adding" : <><Icon name="plus" size={14} />Add</>}
            {busyInvite && <span className="dots" />}
          </button>
        </form>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            <span className="ticon"><Icon name="users" size={16} /></span>
            <h2>Members</h2>
            {members && <span className="chip">{members.length}</span>}
          </div>
          <span className="search-wrap">
            <span className="lead-icon"><Icon name="search" size={14} /></span>
            <input placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} />
          </span>
        </div>

        {!members ? (
          <div aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton-row">
                <Skeleton w={32} h={32} style={{ borderRadius: "50%" }} />
                <div style={{ flex: 1 }}>
                  <Skeleton w={130} h={12} />
                  <div style={{ height: 6 }} />
                  <Skeleton w={190} h={10} />
                </div>
              </div>
            ))}
          </div>
        ) : members.length === 0 ? (
          <Empty icon="search" title="Nobody matches" hint={q ? `No member matches “${q}”.` : undefined} />
        ) : (
          <table className="table">
            <thead>
              <tr><th>Person</th><th>Role</th><th>Plan</th><th>Last seen</th><th /></tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.user_id} className={m.status === "active" ? "" : "dim"}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                      <Avatar name={m.full_name} email={m.email} size="sm" />
                      <div className="who-text">
                        <span className="who-name">{m.full_name || m.email}</span>
                        <span className="who-email">{m.email}</span>
                      </div>
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
                  <td className="muted">{relTime(m.last_login_at)}</td>
                  <td className="right">
                    <button className="btn small ghost" style={{ color: "var(--danger)" }} onClick={() => setRemoving(m)}>
                      <Icon name="trash" size={13} />Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Confirm
        open={!!removing} onClose={() => setRemoving(null)}
        title={`Remove ${removing?.email ?? ""}?`}
        confirmLabel="Remove"
        onConfirm={() => {
          const m = removing;
          setRemoving(null);
          if (m) void act(
            () => api.del(`/api/v1/admin/${slug}/members/${m.user_id}`),
            `${m.email} removed from ${slug}.`,
          );
        }}
      >
        They lose access to this platform immediately. Their account and memberships elsewhere are untouched.
      </Confirm>
    </section>
  );
}
