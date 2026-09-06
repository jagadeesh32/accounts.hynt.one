import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { BarList, ChartCard, SERIES, StackedBar, StatTile, foldToSlots } from "../charts";
import { NoteBanner, useNote } from "../lib/useNote";
import { relTime } from "../ui";
import { DataTable } from "../widgets/DataTable";

interface Member {
  user_id: string; email: string; full_name: string; status: string;
  role: string; rank: number; plan: string | null; plan_status: string | null;
  last_login_at: string | null;
}
interface RoleRow { slug: string; name: string; rank: number; grantable: boolean }
interface PlanRow { slug: string; name: string; price_inr: number; is_default: boolean }

/** Members of one platform. Scoped to the caller's rank on it — a Terminal
 *  admin never sees X-Terminal, and the API enforces that independently. */
export function MembersPage() {
  const { slug = "" } = useParams();
  const [members, setMembers] = useState<Member[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const { note, setNote, act } = useNote();

  const [invite, setInvite] = useState({ email: "", role: "user", plan: "" });
  // "Add existing" is a separate action from "invite", not a smarter version of
  // it: invite creates an account and shows a temporary password, this one
  // grants an account that already exists somewhere in the estate. Conflating
  // them is how you hand a second password to someone who already has one.
  const [grant, setGrant] = useState({ email: "", role: "user", plan: "" });

  const load = useCallback(async () => {
    if (!slug) return;
    const [m, r, p] = await Promise.all([
      api.get<{ members: Member[] }>(`/api/v1/admin/${slug}/members?limit=500`),
      api.get<{ roles: RoleRow[] }>(`/api/v1/admin/${slug}/roles`),
      api.get<{ plans: PlanRow[] }>(`/api/v1/admin/${slug}/plans`),
    ]);
    setMembers(m.members);
    setRoles(r.roles);
    setPlans(p.plans);
  }, [slug]);

  useEffect(() => { void load(); }, [load]);

  const grantable = roles.filter((r) => r.grantable);

  const shape = useMemo(() => {
    const month = Date.now() - 30 * 86400e3;
    const roleMix = new Map<string, number>();
    const planMix = new Map<string, number>();
    for (const m of members) {
      roleMix.set(m.role, (roleMix.get(m.role) ?? 0) + 1);
      planMix.set(m.plan ?? "none", (planMix.get(m.plan ?? "none") ?? 0) + 1);
    }
    return {
      roleMix: [...roleMix.entries()].sort((a, b) => b[1] - a[1]),
      planMix: [...planMix.entries()].map(([plan, count]) => ({ plan, count })),
      active: members.filter((m) => m.last_login_at && new Date(m.last_login_at).getTime() >= month).length,
      never: members.filter((m) => !m.last_login_at).length,
      suspended: members.filter((m) => m.status !== "active").length,
    };
  }, [members]);

  return (
    <section className="page">
      <header className="page-head">
        <h1>Members</h1>
        <p className="muted">
          Who has access to <span className="mono">{slug}</span>, in what role, on which plan.
        </p>
      </header>

      <NoteBanner note={note} />

      <div className="grid-2">
        <div className="card">
          <h2>Invite someone new</h2>
          <p className="muted">
            There is no mail on this box: a new account's temporary password is shown once, here.
          </p>
          <form className="row" onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              const r = await api.post<{ created: boolean; temp_password: string | null }>(
                `/api/v1/admin/${slug}/invite`,
                { email: invite.email, platform: slug, role: invite.role, plan: invite.plan || null },
              );
              if (r.temp_password) {
                setNote({ kind: "ok", text: `Created ${invite.email}. Temporary password: ${r.temp_password}` });
              }
              setInvite({ email: "", role: "user", plan: "" });
            }, `${invite.email} now has access.`, load);
          }}>
            <input type="email" placeholder="person@example.com" required value={invite.email}
                   onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
            <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
              {grantable.map((r) => <option key={r.slug} value={r.slug}>{r.name}</option>)}
            </select>
            <select value={invite.plan} onChange={(e) => setInvite({ ...invite, plan: e.target.value })}>
              <option value="">Default plan</option>
              {plans.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
            </select>
            <button className="btn primary" type="submit">Invite</button>
          </form>
        </div>

        <div className="card">
          <h2>Add an existing account</h2>
          <p className="muted">
            For someone who already has a Hynt account elsewhere — grants access here without
            creating a second account or issuing a new password.
          </p>
          <form className="row" onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              await api.post(`/api/v1/admin/${slug}/members`, {
                email: grant.email, platform: slug, role: grant.role, plan: grant.plan || null,
              });
              setGrant({ email: "", role: "user", plan: "" });
            }, `${grant.email} added to ${slug}.`, load);
          }}>
            <input type="email" placeholder="person@example.com" required value={grant.email}
                   onChange={(e) => setGrant({ ...grant, email: e.target.value })} />
            <select value={grant.role} onChange={(e) => setGrant({ ...grant, role: e.target.value })}>
              {grantable.map((r) => <option key={r.slug} value={r.slug}>{r.name}</option>)}
            </select>
            <select value={grant.plan} onChange={(e) => setGrant({ ...grant, plan: e.target.value })}>
              <option value="">Default plan</option>
              {plans.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
            </select>
            <button className="btn" type="submit">Add</button>
          </form>
        </div>
      </div>

      <div className="kpi-row">
        <StatTile label="Members" value={members.length} hint={`on ${slug}`} />
        <StatTile
          label="Active this month" value={shape.active}
          hint={members.length ? `${Math.round((shape.active / members.length) * 100)}% of members` : "none yet"}
        />
        <StatTile label="Never signed in" value={shape.never} hint="granted, unused" />
        <StatTile
          label="Suspended" value={shape.suspended} upIsGood={false}
          tone={shape.suspended ? "warning" : undefined} hint="account-level, estate-wide"
        />
      </div>

      <div className="viz-grid two">
        <ChartCard
          title="Roles"
          subtitle="Who holds what here."
          table={{ columns: ["Role", "Members"], rows: shape.roleMix.map(([r, c]) => [r, c]) }}
        >
          <BarList rows={shape.roleMix.map(([label, value]) => ({ label, value }))} />
        </ChartCard>

        <ChartCard
          title="Plan mix"
          subtitle="Members per plan, including those holding a role with no subscription."
          table={{ columns: ["Plan", "Members"], rows: shape.planMix.map((p) => [p.plan, p.count]) }}
          right={<Link className="btn small ghost" to={`/admin/${slug}/analytics`}>Analytics</Link>}
        >
          <StackedBar parts={foldToSlots(shape.planMix, (p) => p.count, (p) => p.plan)} />
        </ChartCard>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Members</h2>
          <p className="muted small-text">Role and plan changes take effect on the member's next token — within 15 minutes.</p>
        </div>
        <DataTable
          id={`members-${slug}`}
          rows={members}
          getKey={(m) => m.user_id}
          initialSort="rank"
          exportName={`hynt-${slug}-members`}
          searchPlaceholder="Search name or email"
          note={members.length >= 500 ? "the server returned the first 500 members" : undefined}
          facets={[
            { key: "role", label: "Role", of: (m) => m.role },
            { key: "plan", label: "Plan", of: (m) => m.plan ?? "none" },
            { key: "status", label: "Status", of: (m) => m.status },
          ]}
          columns={[
            {
              key: "person", header: "Person", value: (m) => `${m.full_name} ${m.email}`.trim(),
              render: (m) => (
                <div className={`who-text ${m.status === "active" ? "" : "dim"}`}>
                  <span>{m.full_name || m.email}</span>
                  <span className="who-email">{m.email}</span>
                </div>
              ),
            },
            {
              key: "rank", header: "Role", value: (m) => m.rank,
              render: (m) => (
                <select
                  value={m.role}
                  onChange={(e) => void act(
                    () => api.patch(`/api/v1/admin/${slug}/members/${m.user_id}/role`, { role: e.target.value }),
                    `${m.email} is now ${e.target.value}.`, load,
                  )}
                >
                  {roles.map((r) => (
                    <option key={r.slug} value={r.slug} disabled={!r.grantable && r.slug !== m.role}>{r.name}</option>
                  ))}
                </select>
              ),
            },
            {
              key: "plan", header: "Plan", value: (m) => m.plan ?? "",
              render: (m) => (
                <select
                  value={m.plan ?? ""}
                  onChange={(e) => void act(
                    () => api.post(`/api/v1/admin/${slug}/subscriptions`, {
                      email: m.email, platform: slug, plan: e.target.value, status: "active",
                    }),
                    `${m.email} moved to ${e.target.value}.`, load,
                  )}
                >
                  {plans.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
                </select>
              ),
            },
            {
              key: "seen", header: "Last seen", align: "right", value: (m) => m.last_login_at ?? "",
              render: (m) => <span className="muted">{relTime(m.last_login_at)}</span>,
            },
            {
              key: "remove", header: "", align: "right",
              render: (m) => (
                <button className="btn small danger" onClick={() => {
                  if (!window.confirm(`Remove ${m.email} from ${slug}? Their account stays, they just lose access here.`)) return;
                  void act(
                    () => api.del(`/api/v1/admin/${slug}/members/${m.user_id}`),
                    `${m.email} removed from ${slug}.`, load,
                  );
                }}>Remove</button>
              ),
            },
          ]}
        />
      </div>
    </section>
  );
}
