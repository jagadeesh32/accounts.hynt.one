/**
 * The launcher: every platform this account can reach, with its role and plan.
 *
 * Clicking a tile goes to the platform's own URL. The platform then bounces
 * through /oauth/authorize, finds the live SSO cookie and signs the user in
 * without a second password — which is the point of the whole system.
 */
import { useSession } from "../lib/session";
import { Badge, Empty, formatPrice } from "../components/ui";
import type { AccessEntry } from "../lib/api";

function initials(name: string): string {
  return name
    .split(/[\s-]+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function AppTile({ entry }: { entry: AccessEntry }) {
  const { platform, role, subscription } = entry;
  return (
    <a className="app-tile" href={platform.base_url} target="_self" rel="noreferrer">
      <div className="app-tile-head">
        <span className="app-icon">{initials(platform.name)}</span>
        <div>
          <div className="app-name">{platform.name}</div>
          <div className="faint">{platform.base_url.replace(/^https?:\/\//, "")}</div>
        </div>
      </div>
      <p className="app-desc">{platform.description}</p>
      <div className="app-meta">
        <Badge kind={role}>{role}</Badge>
        {subscription ? (
          <>
            <Badge kind={subscription.status}>{subscription.plan.name}</Badge>
            <span className="faint">
              {formatPrice(subscription.plan.price_cents, subscription.plan.currency)}
              {subscription.plan.price_cents > 0 ? ` / ${subscription.plan.interval}` : ""}
            </span>
          </>
        ) : null}
      </div>
    </a>
  );
}

export default function Dashboard() {
  const { user, access } = useSession();
  if (!user) return null;

  const firstName = user.full_name?.split(" ")[0] || user.email.split("@")[0];

  return (
    <div className="content">
      <h1 className="page-title">Welcome back, {firstName}</h1>
      <p className="page-sub">
        Signed in with <span className="mono">{user.email}</span>. Open any platform below — you
        will not be asked to sign in again.
      </p>

      {access.length === 0 ? (
        <div className="card">
          <Empty>
            You do not have access to any platform yet. An administrator needs to grant it.
          </Empty>
        </div>
      ) : (
        <div className="grid grid-apps">
          {access.map((entry) => (
            <AppTile key={entry.platform.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
