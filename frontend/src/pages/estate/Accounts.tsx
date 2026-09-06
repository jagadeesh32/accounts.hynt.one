import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { ChartCard, SERIES, StackedBar, StatTile } from "../../charts";
import { NoteBanner, useNote } from "../../lib/useNote";
import { relTime } from "../../ui";
import { Drawer, Field } from "../../widgets/Drawer";
import { DataTable } from "../../widgets/DataTable";

interface UserRow {
  id: string; email: string; full_name: string; status: string; is_superadmin: boolean;
  mfa_enabled: boolean; created_at?: string | null; last_login_at: string | null;
  memberships: { platform: string; role: string }[];
}

/** The server caps what it returns; ask for the cap rather than the default 100,
 *  and say so in the footer — a table that filters, sorts and pages over a
 *  silently truncated list is how someone concludes an estate is smaller than
 *  it is. */
const ROW_CAP = 500;
interface PlatformRow { slug: string; name: string }
interface NewUser { email: string; full_name: string; password: string; platform: string; role: string }

const EMPTY: NewUser = { email: "", full_name: "", password: "", platform: "", role: "user" };

export function AccountsPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [platforms, setPlatforms] = useState<PlatformRow[]>([]);
  const [total, setTotal] = useState(0);
  const [draft, setDraft] = useState<NewUser | null>(null);
  const [saving, setSaving] = useState(false);
  const { note, setNote, act } = useNote();

  const load = useCallback(async () => {
    const [u, p] = await Promise.all([
      api.get<{ users: UserRow[]; total: number }>(`/api/v1/superadmin/users?limit=${ROW_CAP}`),
      api.get<{ platforms: PlatformRow[] }>("/api/v1/superadmin/platforms"),
    ]);
    setUsers(u.users);
    setTotal(u.total);
    setPlatforms(p.platforms);
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Derived from what is loaded, and labelled as such — see ROW_CAP.
  const { mfaOn, suspended, superadmins, neverSeen, activeMonth, reach } = useMemo(() => {
    const month = Date.now() - 30 * 86400e3;
    const buckets = { none: 0, one: 0, few: 0, many: 0 };
    for (const u of users) {
      const n = u.memberships.length;
      if (n === 0) buckets.none++;
      else if (n === 1) buckets.one++;
      else if (n <= 3) buckets.few++;
      else buckets.many++;
    }
    return {
      mfaOn: users.filter((u) => u.mfa_enabled).length,
      suspended: users.filter((u) => u.status !== "active").length,
      superadmins: users.filter((u) => u.is_superadmin).length,
      neverSeen: users.filter((u) => !u.last_login_at).length,
      activeMonth: users.filter((u) => u.last_login_at && new Date(u.last_login_at).getTime() >= month).length,
      reach: [
        { label: "No platform", value: buckets.none, color: "var(--panel-3)" },
        { label: "One", value: buckets.one, color: SERIES[0] },
        { label: "Two or three", value: buckets.few, color: SERIES[2] },
        { label: "Four or more", value: buckets.many, color: SERIES[3] },
      ],
    };
  }, [users]);

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

      <div className="kpi-row">
        <StatTile label="Accounts" value={total} hint={users.length < total ? `${users.length} loaded` : "all loaded"} />
        <StatTile
          label="Two-factor" value={`${users.length ? Math.round((mfaOn / users.length) * 100) : 0}%`}
          hint={`${mfaOn} of ${users.length} loaded`}
          tone={users.length && mfaOn / users.length < 0.5 ? "warning" : undefined}
        />
        <StatTile
          label="Suspended" value={suspended} upIsGood={false}
          hint={suspended ? "tokens revoked estate-wide" : "none"}
          tone={suspended ? "warning" : undefined}
        />
        <StatTile label="Superadmins" value={superadmins} hint="can reach every platform" />
        <StatTile label="Never signed in" value={neverSeen} hint="provisioned, unused" />
        <StatTile label="Active this month" value={activeMonth} hint="signed in within 30 days" />
      </div>

      <div className="viz-grid two">
        <ChartCard
          title="Account state"
          subtitle="Across the accounts loaded below."
          table={{ columns: ["State", "Accounts"], rows: [["Active", users.length - suspended], ["Suspended", suspended]] }}
        >
          <StackedBar
            parts={[
              { label: "Active", value: users.length - suspended, color: SERIES[0] },
              { label: "Suspended", value: suspended, color: "var(--st-critical)" },
            ]}
          />
          <StackedBar
            parts={[
              { label: "Two-factor on", value: mfaOn, color: SERIES[2] },
              { label: "Password only", value: users.length - mfaOn, color: "var(--panel-3)" },
            ]}
          />
        </ChartCard>

        <ChartCard
          title="Reach"
          subtitle="How many platforms each account can actually open."
          table={{ columns: ["Platforms", "Accounts"], rows: reach.map((r) => [r.label, r.value]) }}
        >
          <StackedBar parts={reach} />
        </ChartCard>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Accounts</h2>
          <button className="btn primary" onClick={() => setDraft({ ...EMPTY })}>New account</button>
        </div>
        <DataTable
          id="estate-accounts"
          rows={users}
          getKey={(u) => u.id}
          initialSort="seen"
          exportName="hynt-accounts"
          searchPlaceholder="Search name or email"
          note={users.length >= ROW_CAP
            ? `the server returned the newest ${ROW_CAP} of ${total} accounts`
            : `${total} in the estate`}
          facets={[
            { key: "status", label: "Status", of: (u) => u.status },
            { key: "mfa", label: "Two-factor", of: (u) => (u.mfa_enabled ? "enabled" : "password only") },
            { key: "platform", label: "Platform", of: (u) => u.memberships[0]?.platform ?? "none" },
          ]}
          columns={[
            {
              key: "person", header: "Person",
              value: (u) => `${u.full_name} ${u.email}`.trim(),
              render: (u) => (
                <div className="who-text">
                  <span>
                    {u.full_name || u.email}
                    {u.is_superadmin && <span className="chip small">superadmin</span>}
                  </span>
                  <span className="who-email">{u.email}</span>
                </div>
              ),
            },
            {
              key: "access", header: "Access",
              value: (u) => u.memberships.map((m) => `${m.platform}:${m.role}`).join(" "),
              render: (u) => (
                <div className="chips">
                  {u.memberships.map((m) => <span key={m.platform} className="chip">{m.platform}:{m.role}</span>)}
                  {!u.memberships.length && <span className="muted">no platforms</span>}
                </div>
              ),
            },
            {
              key: "status", header: "Status", value: (u) => u.status,
              render: (u) => (
                <>
                  <span className={`chip ${u.status === "active" ? "ok-chip" : "warn"}`}>{u.status}</span>
                  {u.mfa_enabled && <span className="chip small">2FA</span>}
                </>
              ),
            },
            {
              key: "seen", header: "Last seen", align: "right",
              value: (u) => u.last_login_at ?? "",
              render: (u) => <span className="muted">{relTime(u.last_login_at)}</span>,
            },
            {
              key: "actions", header: "", align: "right",
              render: (u) => (
                <div className="row-actions">
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
                </div>
              ),
            },
          ]}
        />
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
