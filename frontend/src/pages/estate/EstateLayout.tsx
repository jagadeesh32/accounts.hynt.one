/**
 * The Estate frame: the stat strip every estate page sits under, plus the
 * routed page itself.
 *
 * The strip is here rather than on each page because it describes the estate,
 * not the page — and loading it once at the layout means moving between
 * Accounts, Clients and Audit does not refetch it five times.
 */
import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { api } from "../../api";

interface Stats {
  users: number; suspended: number; active_sessions: number;
  platforms: number; memberships: number; clients: number;
}

export function EstateLayout() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    void api.get<Stats>("/api/v1/superadmin/stats").then(setStats).catch(() => setStats(null));
  }, []);

  return (
    <>
      {stats && (
        <div className="page">
          <div className="stats">
            <Stat label="Accounts" value={stats.users} />
            <Stat label="Suspended" value={stats.suspended} warn={stats.suspended > 0} />
            <Stat label="Live sessions" value={stats.active_sessions} />
            <Stat label="Platforms" value={stats.platforms} />
            <Stat label="Memberships" value={stats.memberships} />
            <Stat label="Clients" value={stats.clients} />
          </div>
        </div>
      )}
      <Outlet />
    </>
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
