/** Per-platform administration: who is a member, what role, what plan. */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type Membership, type Plan, type Platform, type Role, type Subscription, type User } from "../lib/api";
import { Alert, Badge, Empty, Field, Spinner, formatPrice } from "../components/ui";

type PlatformRow = Platform & { roles: Role[]; member_count: number };
type MemberRow = { membership: Membership; user: User | null; subscription: Subscription | null };

export default function AdminPlatforms() {
  const [platforms, setPlatforms] = useState<PlatformRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const result = await api.admin.platforms();
        setPlatforms(result.platforms);
        setSelected((current) => current ?? result.platforms[0]?.slug ?? null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load platforms.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  if (loading) return <div className="content"><Empty><Spinner /></Empty></div>;

  const active = platforms.find((p) => p.slug === selected);

  return (
    <div className="content">
      <h1 className="page-title">Platforms</h1>
      <p className="page-sub">Members, roles and plans, one platform at a time.</p>

      {error ? <Alert kind="error">{error}</Alert> : null}

      <div className="tabs">
        {platforms.map((platform) => (
          <button
            key={platform.slug}
            className={`tab${platform.slug === selected ? " active" : ""}`}
            onClick={() => setSelected(platform.slug)}
          >
            {platform.name}
            <span className="faint" style={{ marginLeft: 7 }}>{platform.member_count}</span>
          </button>
        ))}
      </div>

      {active ? <PlatformPanel platform={active} /> : <Empty>No platforms configured.</Empty>}
    </div>
  );
}

function PlatformPanel({ platform }: { platform: PlatformRow }) {
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [memberResult, planResult] = await Promise.all([
        api.admin.members(platform.slug),
        api.admin.plans(platform.slug),
      ]);
      setMembers(memberResult.members);
      setPlans(planResult.plans);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this platform.");
    } finally {
      setLoading(false);
    }
  }, [platform.slug]);

  useEffect(() => {
    void load();
  }, [load]);

  async function changeRole(userId: string, role: string) {
    try {
      await api.admin.updateMember(platform.slug, userId, { role });
      setNotice("Role updated.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the role.");
    }
  }

  async function changePlan(userId: string, plan: string) {
    try {
      await api.admin.setSubscription(platform.slug, userId, plan);
      setNotice("Plan updated.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the plan.");
    }
  }

  async function removeMember(userId: string, email: string) {
    try {
      await api.admin.removeMember(platform.slug, userId);
      setNotice(`Removed ${email} from ${platform.name}.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove the member.");
    }
  }

  return (
    <>
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      <AddMember platform={platform} onAdded={(m) => { setNotice(m); void load(); }} />

      <div className="card">
        <div className="card-head">
          <div>
            <h2 className="card-title">Members</h2>
            <p className="card-sub">
              Removing someone here revokes their access to {platform.name} only.
            </p>
          </div>
        </div>

        {loading ? (
          <Empty><Spinner /></Empty>
        ) : members.length === 0 ? (
          <Empty>Nobody has access to {platform.name} yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th style={{ width: 150 }}>Role</th>
                  <th style={{ width: 170 }}>Plan</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {members.map(({ membership, user, subscription }) => (
                  <tr key={membership.id}>
                    <td>
                      <div style={{ fontWeight: 550 }}>{user?.full_name || "—"}</div>
                      <div className="faint mono">{user?.email ?? membership.user_id}</div>
                    </td>
                    <td>
                      <select
                        value={membership.role.code}
                        onChange={(e) => void changeRole(membership.user_id, e.target.value)}
                      >
                        {platform.roles.map((role) => (
                          <option key={role.id} value={role.code}>{role.name}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select
                        value={subscription?.plan.code ?? ""}
                        onChange={(e) => void changePlan(membership.user_id, e.target.value)}
                      >
                        {subscription ? null : <option value="">No plan</option>}
                        {plans.map((plan) => (
                          <option key={plan.id} value={plan.code}>
                            {plan.name} — {formatPrice(plan.price_cents, plan.currency)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => void removeMember(membership.user_id, user?.email ?? "")}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">Plans on {platform.name}</h2>
        <div className="grid grid-plans" style={{ marginTop: 14 }}>
          {plans.map((plan) => (
            <div className={`plan${plan.is_default ? " current" : ""}`} key={plan.id}>
              <div className="row-between">
                <strong>{plan.name}</strong>
                {plan.is_default ? <Badge kind="active">default</Badge> : null}
              </div>
              <div className="plan-price">
                {formatPrice(plan.price_cents, plan.currency)}
                {plan.price_cents > 0 ? <small> / {plan.interval}</small> : null}
              </div>
              <ul className="plan-features">
                {plan.features.map((feature) => <li key={feature}>{feature}</li>)}
              </ul>
              {plan.entitlements.length > 0 ? (
                <div className="faint">
                  Unlocks: <span className="mono">{plan.entitlements.join(", ")}</span>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">Roles</h2>
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr><th>Role</th><th>Rank</th><th>Permissions</th></tr>
            </thead>
            <tbody>
              {platform.roles.map((role) => (
                <tr key={role.id}>
                  <td>
                    <Badge kind={role.code}>{role.name}</Badge>
                    <div className="faint" style={{ marginTop: 4 }}>{role.description}</div>
                  </td>
                  <td className="muted">{role.rank}</td>
                  <td className="mono faint">{role.permissions.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function AddMember({ platform, onAdded }: { platform: PlatformRow; onAdded: (m: string) => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("user");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.admin.addMember(platform.slug, email.trim(), role);
      onAdded(`${email} now has ${role} access to ${platform.name}.`);
      setEmail("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not grant access.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <h2 className="card-title">Grant access</h2>
      {error ? <Alert kind="error">{error}</Alert> : null}
      <div className="row" style={{ alignItems: "flex-end", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 260px" }}>
          <Field label="Email of an existing account">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
        </div>
        <div style={{ width: 170 }}>
          <Field label="Role">
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {platform.roles.map((r) => (
                <option key={r.id} value={r.code}>{r.name}</option>
              ))}
            </select>
          </Field>
        </div>
        <button className="btn btn-primary" disabled={busy || !email} style={{ marginBottom: 1 }}>
          {busy ? <Spinner /> : null} Grant
        </button>
      </div>
    </form>
  );
}
