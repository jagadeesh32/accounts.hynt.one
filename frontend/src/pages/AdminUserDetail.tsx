/**
 * One account, under full superadmin control.
 *
 * Four tabs answer the four questions worth asking about an account: what can
 * it reach, where is it signed in, what has it been doing, and how do I stop
 * all of it. Every destructive action here publishes a revocation, so it takes
 * effect on the platforms within seconds rather than at the next token expiry.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type ActivityEntry,
  type Platform,
  type SessionRow,
  type UserOverview,
} from "../lib/api";
import { useSession } from "../lib/session";
import {
  Alert,
  Badge,
  Empty,
  Field,
  Spinner,
  describeAgent,
  formatDate,
  relativeTime,
} from "../components/ui";

type Tab = "access" | "devices" | "activity" | "danger";

export default function AdminUserDetail() {
  const { userId = "" } = useParams();
  const navigate = useNavigate();
  const { user: me } = useSession();

  const [data, setData] = useState<UserOverview | null>(null);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [tab, setTab] = useState<Tab>("access");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [overview, platformList] = await Promise.all([
        api.admin.userOverview(userId),
        api.platforms(),
      ]);
      setData(overview);
      setPlatforms(platformList.platforms);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this account.");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act<T>(fn: () => Promise<T>, message: string) {
    setError(null);
    try {
      await fn();
      setNotice(message);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That action failed.");
    }
  }

  if (loading) return <div className="content"><Empty><Spinner /></Empty></div>;
  if (!data) {
    return (
      <div className="content">
        <Alert kind="error">{error ?? "Account not found."}</Alert>
        <Link className="btn" to="/admin/users">Back to users</Link>
      </div>
    );
  }

  const isSelf = data.user.id === me?.id;

  return (
    <div className="content">
      <Link className="faint" to="/admin/users">← All users</Link>

      <div className="row-between" style={{ marginTop: 10, marginBottom: 20 }}>
        <div>
          <h1 className="page-title">{data.user.full_name || data.user.email}</h1>
          <p className="page-sub" style={{ margin: 0 }}>
            <span className="mono">{data.user.email}</span>
            {data.organization ? <> · {data.organization.name}</> : null}
          </p>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <Badge kind={data.user.status}>{data.user.status}</Badge>
          {data.user.is_superadmin ? <Badge kind="superadmin">superadmin</Badge> : null}
        </div>
      </div>

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}
      {isSelf ? (
        <Alert kind="info">
          This is your own account. Destructive actions are blocked — locking out the last
          superadmin has no recovery path through this console.
        </Alert>
      ) : null}

      <div className="tabs">
        {(["access", "devices", "activity", "danger"] as Tab[]).map((name) => (
          <button key={name} className={`tab${tab === name ? " active" : ""}`}
                  onClick={() => setTab(name)}>
            {name === "access" ? "Platform access"
              : name === "devices" ? `Devices (${data.sessions.length})`
              : name === "activity" ? "Activity"
              : "Revoke & delete"}
          </button>
        ))}
      </div>

      {tab === "access" ? (
        <AccessTab data={data} platforms={platforms} onAct={act} />
      ) : tab === "devices" ? (
        <DevicesTab data={data} disabled={isSelf} onAct={act} />
      ) : tab === "activity" ? (
        <ActivityTab userId={userId} />
      ) : (
        <DangerTab
          data={data}
          disabled={isSelf}
          onAct={act}
          onDeleted={() => navigate("/admin/users", { replace: true })}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- access
function AccessTab({
  data,
  platforms,
  onAct,
}: {
  data: UserOverview;
  platforms: Platform[];
  onAct: <T>(fn: () => Promise<T>, message: string) => Promise<void>;
}) {
  const granted = new Map(data.access.map((a) => [a.membership.platform.slug, a]));
  const [grantSlug, setGrantSlug] = useState("");
  const [grantRole, setGrantRole] = useState("user");

  const ungranted = platforms.filter((p) => {
    const entry = granted.get(p.slug);
    return !entry || !entry.membership.active;
  });

  return (
    <>
      <div className="card">
        <h2 className="card-title">Platforms this account can reach</h2>
        <p className="card-sub" style={{ marginBottom: 14 }}>
          Revoking a platform deactivates the membership and kills the token the user is
          currently holding for it — the other platforms are untouched.
        </p>

        {data.access.length === 0 ? (
          <Empty>No platform access.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Platform</th><th>Role</th><th>Plan</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {data.access.map(({ membership, subscription }) => (
                  <tr key={membership.id}>
                    <td>
                      <div style={{ fontWeight: 550 }}>{membership.platform.name}</div>
                      <div className="faint mono">{membership.platform.slug}</div>
                    </td>
                    <td>
                      <select
                        value={membership.role.code}
                        onChange={(e) =>
                          void onAct(
                            () =>
                              api.admin.grantPlatform(
                                data.user.id,
                                membership.platform.slug,
                                e.target.value,
                              ),
                            `Role changed on ${membership.platform.name}.`,
                          )
                        }
                      >
                        {["admin", "staff", "user"].map((code) => (
                          <option key={code} value={code}>{code}</option>
                        ))}
                      </select>
                    </td>
                    <td className="muted">
                      {subscription ? (
                        <>
                          {subscription.plan.name}{" "}
                          <Badge kind={subscription.status}>{subscription.status}</Badge>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <Badge kind={membership.active ? "active" : "suspended"}>
                        {membership.active ? "active" : "revoked"}
                      </Badge>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {membership.active ? (
                        <button
                          className="btn btn-sm btn-danger"
                          onClick={() =>
                            void onAct(
                              () => api.admin.revokePlatform(data.user.id, membership.platform.slug),
                              `Revoked ${membership.platform.name} — their token stops working within seconds.`,
                            )
                          }
                        >
                          Revoke access
                        </button>
                      ) : (
                        <button
                          className="btn btn-sm"
                          onClick={() =>
                            void onAct(
                              () =>
                                api.admin.grantPlatform(
                                  data.user.id,
                                  membership.platform.slug,
                                  membership.role.code,
                                ),
                              `Restored ${membership.platform.name}.`,
                            )
                          }
                        >
                          Restore
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {ungranted.length > 0 ? (
        <div className="card">
          <h2 className="card-title">Grant another platform</h2>
          <div className="row" style={{ alignItems: "flex-end", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
            <div style={{ minWidth: 220 }}>
              <Field label="Platform">
                <select value={grantSlug} onChange={(e) => setGrantSlug(e.target.value)}>
                  <option value="">Choose…</option>
                  {ungranted.map((p) => (
                    <option key={p.slug} value={p.slug}>{p.name}</option>
                  ))}
                </select>
              </Field>
            </div>
            <div style={{ width: 160 }}>
              <Field label="Role">
                <select value={grantRole} onChange={(e) => setGrantRole(e.target.value)}>
                  {["admin", "staff", "user"].map((code) => (
                    <option key={code} value={code}>{code}</option>
                  ))}
                </select>
              </Field>
            </div>
            <button
              className="btn btn-primary"
              disabled={!grantSlug}
              style={{ marginBottom: 1 }}
              onClick={() =>
                void onAct(
                  () => api.admin.grantPlatform(data.user.id, grantSlug, grantRole),
                  `Granted ${grantSlug}.`,
                )
              }
            >
              Grant
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}

// -------------------------------------------------------------------------- devices
function DevicesTab({
  data,
  disabled,
  onAct,
}: {
  data: UserOverview;
  disabled: boolean;
  onAct: <T>(fn: () => Promise<T>, message: string) => Promise<void>;
}) {
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">Signed-in devices</h2>
          <p className="card-sub">
            Every live SSO session. Ending one signs out that device only.
          </p>
        </div>
        <span className="faint">token version {data.token_version}</span>
      </div>

      {data.sessions.length === 0 ? (
        <Empty>No active sessions.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Device</th><th>IP address</th><th>Last active</th>
                <th>Signed in</th><th>Expires</th><th />
              </tr>
            </thead>
            <tbody>
              {data.sessions.map((row: SessionRow) => (
                <tr key={row.id}>
                  <td>
                    <div>{describeAgent(row.user_agent)}</div>
                    <div className="faint mono" style={{ maxWidth: 300, overflow: "hidden",
                                                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {row.user_agent}
                    </div>
                  </td>
                  <td className="mono">{row.ip_address ?? "—"}</td>
                  <td className="muted">{relativeTime(row.last_seen_at)}</td>
                  <td className="muted">{formatDate(row.created_at)}</td>
                  <td className="muted">{formatDate(row.expires_at)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="btn btn-sm btn-danger"
                      disabled={disabled}
                      onClick={() =>
                        void onAct(
                          () => api.admin.endUserSession(data.user.id, row.id),
                          "Device signed out.",
                        )
                      }
                    >
                      Sign out
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------- activity
const ACTIVITY_FILTERS = [
  { label: "Everything", value: "" },
  { label: "Sign-ins", value: "auth.login.success" },
  { label: "Failed sign-ins", value: "auth.login.failed" },
  { label: "Tokens issued", value: "oauth.token.issued" },
  { label: "Access denied", value: "oauth.authorize.denied" },
  { label: "Sessions revoked", value: "auth.sessions.revoked" },
  { label: "Role changes", value: "admin.membership.role_changed" },
];

function ActivityTab({ userId }: { userId: string }) {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void api.admin
      .userActivity(userId, { offset, action: action || undefined })
      .then((result) => {
        if (cancelled) return;
        setEntries(result.entries);
        setTotal(result.total);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [userId, offset, action]);

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">Complete activity</h2>
          <p className="card-sub">
            What this account did, and what was done to it — both directions.
          </p>
        </div>
        <select value={action} onChange={(e) => { setOffset(0); setAction(e.target.value); }}
                style={{ maxWidth: 220 }}>
          {ACTIVITY_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <Empty><Spinner /></Empty>
      ) : entries.length === 0 ? (
        <Empty>Nothing recorded.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>When</th><th>Action</th><th>Platform</th><th>IP</th><th>Device</th><th>Details</th></tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>{formatDate(entry.created_at)}</td>
                  <td>
                    <Badge kind={
                      entry.action.includes("failed") || entry.action.includes("denied")
                        ? "suspended"
                        : entry.action.includes("success") || entry.action.includes("issued")
                          ? "active"
                          : "admin"
                    }>
                      {entry.action}
                    </Badge>
                  </td>
                  <td className="muted">{entry.platform_slug ?? "—"}</td>
                  <td className="mono">{entry.ip_address ?? "—"}</td>
                  <td className="faint">{describeAgent(entry.user_agent ?? null)}</td>
                  <td className="faint mono" style={{ maxWidth: 260, overflow: "hidden",
                                                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {Object.keys(entry.meta ?? {}).length ? JSON.stringify(entry.meta) : "—"}
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
                  onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
          <span className="faint">{offset + 1}–{Math.min(offset + 50, total)} of {total}</span>
          <button className="btn btn-sm" disabled={offset + 50 >= total}
                  onClick={() => setOffset(offset + 50)}>Next</button>
        </div>
      ) : null}
    </div>
  );
}

// --------------------------------------------------------------------------- danger
function DangerTab({
  data,
  disabled,
  onAct,
  onDeleted,
}: {
  data: UserOverview;
  disabled: boolean;
  onAct: <T>(fn: () => Promise<T>, message: string) => Promise<void>;
  onDeleted: () => void;
}) {
  const [reason, setReason] = useState("");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function remove() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.admin.deleteUser(data.user.id, confirmEmail.trim().toLowerCase());
      onDeleted();
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Could not delete the account.");
      setDeleting(false);
    }
  }

  return (
    <>
      <div className="card">
        <h2 className="card-title">Suspend</h2>
        <p className="card-sub" style={{ marginBottom: 14 }}>
          Blocks sign-in and ends every session. Reversible — the account and all its data stay.
        </p>
        {data.user.status === "suspended" ? (
          <button className="btn" disabled={disabled}
                  onClick={() => void onAct(
                    () => api.admin.updateUser(data.user.id, { status: "active" }),
                    "Account reinstated.")}>
            Reinstate account
          </button>
        ) : (
          <button className="btn btn-danger" disabled={disabled}
                  onClick={() => void onAct(
                    () => api.admin.updateUser(data.user.id, { status: "suspended" }),
                    "Account suspended and signed out everywhere.")}>
            Suspend account
          </button>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">Revoke all access now</h2>
        <p className="card-sub" style={{ marginBottom: 14 }}>
          Ends every session, withdraws every refresh token, and publishes a revocation so all
          three platforms stop honouring the tokens already in their browser — within seconds,
          not at the next expiry. The account itself stays; they can sign in again.
        </p>
        <Field label="Reason (recorded in the audit log)">
          <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
                 placeholder="e.g. suspected credential compromise" />
        </Field>
        <div style={{ marginTop: 14 }}>
          <button className="btn btn-danger" disabled={disabled}
                  onClick={() => void onAct(
                    () => api.admin.revokeAll(data.user.id, reason || "manual_revocation"),
                    "All access revoked. The platforms will stop accepting their tokens within seconds.")}>
            Revoke everything
          </button>
        </div>
      </div>

      <div className="card" style={{ borderColor: "rgba(239,68,68,0.4)" }}>
        <h2 className="card-title" style={{ color: "var(--danger)" }}>Delete permanently</h2>
        <p className="card-sub" style={{ marginBottom: 14 }}>
          Removes the account, its memberships and its subscriptions. The audit trail survives —
          the record of what happened outlives the account it happened to. This cannot be undone.
        </p>
        {deleteError ? <Alert kind="error">{deleteError}</Alert> : null}
        <Field label={`Type ${data.user.email} to confirm`}>
          <input type="text" value={confirmEmail} onChange={(e) => setConfirmEmail(e.target.value)}
                 placeholder={data.user.email} autoComplete="off" />
        </Field>
        <div style={{ marginTop: 14 }}>
          <button
            className="btn btn-danger"
            disabled={disabled || deleting || confirmEmail.trim().toLowerCase() !== data.user.email}
            onClick={() => void remove()}
          >
            {deleting ? <Spinner /> : null} Delete this account
          </button>
        </div>
      </div>
    </>
  );
}
