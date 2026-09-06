/**
 * The audit log.
 *
 * The server decides how far back this reaches (the row cap) and can pre-filter
 * by action; everything else — search, facets, sort, paging, CSV — happens over
 * what came back. That split is stated in the footer on purpose: a filter that
 * silently only searches the last hundred rows is a trap, and the charts above
 * describe the same loaded window, not all of history.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { BarList, ChartCard, Heatmap, SERIES, StatTile, TimeSeries } from "../../charts";
import { DataTable } from "../../widgets/DataTable";

interface AuditRow {
  at: string; action: string; actor: string | null; target: string | null;
  ip: string | null; meta?: Record<string, unknown> | null;
}

const CAPS = [100, 250, 500];

export function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [action, setAction] = useState("");
  const [limit, setLimit] = useState(250);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    const query = new URLSearchParams({ limit: String(limit) });
    if (action) query.set("action", action);
    try {
      setRows((await api.get<{ events: AuditRow[] }>(`/api/v1/superadmin/audit?${query}`)).events);
    } finally {
      setBusy(false);
    }
  }, [action, limit]);

  useEffect(() => { void load(); }, [load]);

  // Built from what actually loaded, so the list reflects this estate rather
  // than a hardcoded catalogue that drifts from the backend.
  const actions = useMemo(() => [...new Set(rows.map((e) => e.action))].sort(), [rows]);

  const { daily, byAction, heat, failures, span } = useMemo(() => {
    const perDay = new Map<string, { all: number; bad: number }>();
    const perAction = new Map<string, number>();
    const cells = new Map<string, number>();
    let bad = 0;
    for (const e of rows) {
      const at = new Date(e.at);
      const day = at.toISOString().slice(0, 10);
      const isBad = e.action === "login.failed" || e.action === "login.mfa_failed";
      if (isBad) bad++;
      const row = perDay.get(day) ?? { all: 0, bad: 0 };
      row.all++;
      if (isBad) row.bad++;
      perDay.set(day, row);
      perAction.set(e.action, (perAction.get(e.action) ?? 0) + 1);
      const k = `${at.getDay()}-${at.getHours()}`;
      cells.set(k, (cells.get(k) ?? 0) + 1);
    }
    const days = [...perDay.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return {
      daily: days.map(([d, v]) => ({ d, all: v.all, bad: v.bad })),
      byAction: [...perAction.entries()].sort((a, b) => b[1] - a[1]),
      heat: [...cells.entries()].map(([k, v]) => {
        const [dow, hour] = k.split("-").map(Number);
        return { dow, hour, v };
      }),
      failures: bad,
      span: days.length ? `${days[0][0]} → ${days[days.length - 1][0]}` : "—",
    };
  }, [rows]);

  return (
    <section className={`page analytics ${busy ? "reloading" : ""}`}>
      <header className="page-head">
        <h1>Audit</h1>
        <p className="muted">
          Every administrative action, and who took it. Written on the server, so a change made
          directly in the database does not appear here.
        </p>
      </header>

      <div className="kpi-row">
        <StatTile label="Events loaded" value={rows.length} hint={span} />
        <StatTile label="Distinct actions" value={actions.length} hint="in this slice" />
        <StatTile
          label="Rejected sign-ins" value={failures} upIsGood={false}
          hint={rows.length ? `${Math.round((failures / rows.length) * 100)}% of events` : "none"}
          tone={rows.length && failures / rows.length > 0.3 ? "warning" : undefined}
        />
        <StatTile
          label="Distinct actors" value={new Set(rows.map((r) => r.actor).filter(Boolean)).size}
          hint="named accounts"
        />
      </div>

      <div className="viz-grid">
        <ChartCard
          title="Events per day"
          subtitle="Everything audited in the loaded slice, with rejected sign-ins called out beneath it."
          table={{ columns: ["Day", "Events", "Rejected"], rows: daily.map((d) => [d.d, d.all, d.bad]) }}
        >
          <TimeSeries
            data={daily}
            series={[
              { key: "all", label: "All events", color: SERIES[0] },
              { key: "bad", label: "Rejected sign-ins", color: SERIES[7] },
            ]}
          />
        </ChartCard>

        <ChartCard
          title="What happened"
          subtitle="Actions by frequency in the loaded slice."
          table={{ columns: ["Action", "Events"], rows: byAction.map(([a, c]) => [a, c]) }}
        >
          <BarList rows={byAction.slice(0, 9).map(([label, value]) => ({ label, value }))} />
        </ChartCard>
      </div>

      <ChartCard
        title="When it happened"
        subtitle="Weekday by hour, in your own timezone."
        table={{
          columns: ["Weekday", "Hour", "Events"],
          rows: [...heat].sort((a, b) => b.v - a.v).slice(0, 40).map((c) => [
            ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][c.dow],
            `${String(c.hour).padStart(2, "0")}:00`, c.v,
          ]),
        }}
      >
        <Heatmap cells={heat} />
      </ChartCard>

      <div className="card">
        <div className="card-head">
          <h2>Events</h2>
          <div className="filters">
            <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action, filtered by the server">
              <option value="">Every action (server-side)</option>
              {actions.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} aria-label="How far back to load">
              {CAPS.map((n) => <option key={n} value={n}>Load last {n}</option>)}
            </select>
          </div>
        </div>

        <DataTable
          id="estate-audit"
          rows={rows}
          getKey={(e) => `${e.at}-${e.action}-${e.target ?? ""}-${e.ip ?? ""}`}
          initialSort="at"
          loading={busy}
          exportName="hynt-audit"
          searchPlaceholder="Search actor, target or IP"
          note={`the server returned the newest ${limit}; widen the cap to search further back`}
          facets={[
            { key: "action", label: "Action", of: (e) => e.action },
            { key: "actor", label: "Actor", of: (e) => e.actor ?? "system" },
          ]}
          columns={[
            {
              key: "at", header: "When", value: (e) => e.at,
              render: (e) => <span className="muted">{new Date(e.at).toLocaleString()}</span>,
            },
            {
              key: "action", header: "Action", value: (e) => e.action,
              render: (e) => <span className="mono">{e.action}</span>,
            },
            { key: "actor", header: "Actor", value: (e) => e.actor ?? "—" },
            {
              key: "target", header: "Target", value: (e) => e.target ?? "",
              render: (e) => <span className="muted">{e.target ?? "—"}</span>,
            },
            {
              key: "ip", header: "IP", value: (e) => e.ip ?? "",
              render: (e) => <span className="mono muted">{e.ip ?? "—"}</span>,
            },
            {
              key: "meta", header: "Detail",
              value: (e) => (e.meta && Object.keys(e.meta).length ? JSON.stringify(e.meta) : ""),
              render: (e) => (
                e.meta && Object.keys(e.meta).length
                  ? <span className="mono small-text">{Object.entries(e.meta).map(([k, v]) => `${k}=${String(v)}`).join(" ")}</span>
                  : <span className="muted">—</span>
              ),
            },
          ]}
        />
      </div>
    </section>
  );
}
