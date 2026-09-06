/**
 * The estate analytics board.
 *
 * One window control at the top scopes everything below it — every tile, chart
 * and table on this page describes the same slice, so two numbers on the screen
 * can never disagree about which days they cover.
 *
 * The aggregates come from the database (GROUP BY over the whole window), not
 * from a page of rows this browser happened to load. The readings beside them
 * come from lib/insights.ts, and every one shows the arithmetic it used.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import {
  BarList, ChartCard, Heatmap, Meter, SERIES, StackedBar, StatTile, TimeSeries,
  fmtInr, fmtInt, foldToSlots,
} from "../../charts";
import { Segmented, type SegOption } from "../../ui";
import { DataTable } from "../../widgets/DataTable";
import { change, estateInsights, sum, values, type EstatePayload, type Insight } from "../../lib/insights";

type Window = "7" | "30" | "90" | "365";

const WINDOWS: SegOption<Window>[] = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
];

export function AnalyticsPage() {
  const [days, setDays] = useState<Window>("30");
  const [data, setData] = useState<EstatePayload | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api.get<EstatePayload>(`/api/v1/superadmin/analytics?days=${days}`));
      setFailed(null);
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "Could not load analytics");
    } finally {
      setBusy(false);
    }
  }, [days]);

  useEffect(() => { void load(); }, [load]);

  if (!data) {
    return (
      <section className="page">
        <header className="page-head">
          <h1>Analytics</h1>
          <p className="muted">Reading the estate…</p>
        </header>
        {failed && <div className="alert error">{failed}</div>}
      </section>
    );
  }

  const t = data.totals;
  const logins = sum(data.series.logins);
  const failures = sum(data.series.failures);
  const signups = sum(data.series.signups);
  const activePeak = Math.max(...values(data.series.active_users), 0);
  const window = `vs previous ${data.window_days}d`;
  const insights = estateInsights(data);

  return (
    // While a new window loads, the charts hold their last render at reduced
    // opacity: no skeleton, no layout jump, no flash of an empty board.
    <section className={`page analytics ${busy ? "reloading" : ""}`}>
      <header className="page-head">
        <div className="head-row">
          <div>
            <h1>Analytics</h1>
            <p className="muted">
              Every figure below is aggregated in the database over the selected window — not from
              the rows any one table has loaded.
            </p>
          </div>
          <Segmented options={WINDOWS} value={days} onChange={setDays} />
        </div>
      </header>

      {failed && <div className="alert error">{failed}</div>}

      <div className="kpi-row">
        <StatTile
          label="Accounts" value={t.users}
          hint={`${t.suspended} suspended`}
          delta={change(signups, data.previous.signups)} deltaLabel={window}
          trend={values(data.series.signups)}
        />
        <StatTile
          label="Signed in" value={logins}
          delta={change(logins, data.previous.logins)} deltaLabel={window}
          trend={values(data.series.logins)}
        />
        <StatTile
          label="Distinct people" value={activePeak}
          hint="busiest day in the window"
          delta={change(sum(data.series.active_users), data.previous.active_users)} deltaLabel={window}
          trend={values(data.series.active_users)}
        />
        <StatTile
          label="Failed sign-ins" value={failures}
          upIsGood={false}
          delta={change(failures, data.previous.failures)} deltaLabel={window}
          trend={values(data.series.failures)}
          tone={failures > 0 && failures / Math.max(1, failures + logins) > 0.3 ? "warning" : undefined}
        />
        <StatTile label="Monthly revenue" value={fmtInr(t.mrr_inr)} hint={`${t.subscriptions} subscriptions`} />
        <StatTile label="Live sessions" value={t.live_sessions} hint={`${t.memberships} memberships`} />
      </div>

      <InsightPanel insights={insights} />

      <div className="viz-grid">
        <ChartCard
          title="Sign-ins and rejections"
          subtitle="Accepted against rejected, per day. Both are attempts on the same door, so they share one axis."
          table={{
            columns: ["Day", "Accepted", "Rejected"],
            rows: data.series.logins.map((p, i) => [p.d, p.v, data.series.failures[i]?.v ?? 0]),
          }}
        >
          <TimeSeries
            data={data.series.logins.map((p, i) => ({
              d: p.d, ok: p.v, bad: data.series.failures[i]?.v ?? 0,
            }))}
            series={[
              { key: "ok", label: "Accepted", color: SERIES[0] },
              { key: "bad", label: "Rejected", color: SERIES[7] },
            ]}
          />
        </ChartCard>

        <ChartCard
          title="New accounts"
          subtitle="Created per day, from the accounts table itself."
          table={{ columns: ["Day", "Created"], rows: data.series.signups.map((p) => [p.d, p.v]) }}
        >
          <TimeSeries
            data={data.series.signups}
            series={[{ key: "v", label: "New accounts", color: SERIES[0] }]}
            area
          />
        </ChartCard>

        <ChartCard
          title="Administrative actions"
          subtitle="Everything that changed authority — grants, role changes, key rotations, suspensions."
          table={{ columns: ["Day", "Actions"], rows: data.series.admin_actions.map((p) => [p.d, p.v]) }}
        >
          <TimeSeries
            data={data.series.admin_actions}
            series={[{ key: "v", label: "Admin actions", color: SERIES[2] }]}
            area
          />
        </ChartCard>

        <ChartCard
          title="When the estate is used"
          subtitle="Every audited event by weekday and hour, in your browser's timezone reading of UTC stamps."
          table={{
            columns: ["Weekday", "Hour", "Events"],
            rows: [...data.heatmap]
              .sort((a, b) => b.v - a.v).slice(0, 40)
              .map((c) => [["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][c.dow], `${String(c.hour).padStart(2, "0")}:00`, c.v]),
          }}
        >
          <Heatmap cells={data.heatmap} />
        </ChartCard>
      </div>

      <div className="viz-grid three">
        <ChartCard title="Two-factor coverage" subtitle="Set by each account holder, not by an admin.">
          <StackedBar
            parts={[
              { label: "Enabled", value: data.mfa.enabled, color: SERIES[0] },
              { label: "Password only", value: data.mfa.disabled, color: "var(--panel-3)" },
            ]}
          />
          <Meter value={data.mfa.enabled} total={t.users} label="Accounts protected" />
        </ChartCard>

        <ChartCard title="Last seen" subtitle="How recently each account signed in.">
          <StackedBar
            parts={[
              { label: "Today", value: data.recency.day, color: SERIES[0] },
              { label: "This week", value: Math.max(0, data.recency.week - data.recency.day), color: SERIES[2] },
              { label: "This month", value: Math.max(0, data.recency.month - data.recency.week), color: SERIES[3] },
              { label: "Older", value: Math.max(0, data.recency.total - data.recency.month - data.recency.never), color: SERIES[1] },
              { label: "Never", value: data.recency.never, color: "var(--panel-3)" },
            ]}
            total={data.recency.total}
          />
        </ChartCard>

        <ChartCard title="Estate composition" subtitle="What the identity provider is actually holding.">
          <div className="mini-facts">
            <div><b>{fmtInt(t.platforms)}</b><span>platforms</span></div>
            <div><b>{fmtInt(t.memberships)}</b><span>memberships</span></div>
            <div><b>{fmtInt(t.clients)}</b><span>OAuth clients</span></div>
            <div><b>{fmtInt(t.superadmins)}</b><span>superadmins</span></div>
          </div>
        </ChartCard>
      </div>

      <div className="viz-grid three">
        <ChartCard
          title="Most frequent events"
          subtitle={`Audited actions over ${data.window_days} days.`}
          table={{ columns: ["Action", "Count"], rows: data.actions.map((a) => [a.action, a.count]) }}
        >
          <BarList rows={data.actions.slice(0, 8).map((a) => ({ label: a.action, value: a.count }))} />
        </ChartCard>

        <ChartCard
          title="Busiest administrators"
          subtitle="Who changed things, excluding their own sign-ins."
          table={{ columns: ["Actor", "Actions"], rows: data.top_actors.map((a) => [a.actor, a.count]) }}
        >
          <BarList rows={data.top_actors.map((a) => ({ label: a.actor, value: a.count }))} />
        </ChartCard>

        <ChartCard
          title="Where failures come from"
          subtitle="Rejected sign-ins by source address, and how many accounts each tried."
          table={{
            columns: ["Address", "Failures", "Accounts tried"],
            rows: data.failure_sources.map((f) => [f.ip, f.count, f.accounts]),
          }}
        >
          <BarList
            color="var(--st-critical)"
            rows={data.failure_sources.map((f) => ({
              label: f.ip,
              value: f.count,
              hint: `${f.accounts} account${f.accounts === 1 ? "" : "s"} tried`,
            }))}
          />
        </ChartCard>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Platforms</h2>
          <p className="muted small-text">Members, engagement and revenue per platform.</p>
        </div>
        <DataTable
          id="estate-platforms"
          rows={data.platforms}
          getKey={(p) => p.slug}
          initialSort="members"
          exportName="hynt-platforms"
          searchPlaceholder="Search platforms"
          columns={[
            {
              key: "name", header: "Platform", value: (p) => p.name,
              render: (p) => (
                <div className="who-text">
                  <span>{p.name}</span>
                  <span className="who-email mono">{p.slug}</span>
                </div>
              ),
            },
            { key: "members", header: "Members", value: (p) => p.members, align: "right" },
            {
              key: "active", header: "Active 30d", value: (p) => p.active_30d, align: "right",
              render: (p) => (
                <span className="cell-ratio">
                  {p.active_30d}
                  <i>{p.members ? Math.round((p.active_30d / p.members) * 100) : 0}%</i>
                </span>
              ),
            },
            { key: "paying", header: "Paying", value: (p) => p.paying, align: "right" },
            {
              key: "mrr", header: "Monthly", value: (p) => p.mrr_inr, align: "right",
              render: (p) => fmtInr(p.mrr_inr),
            },
            {
              key: "roles", header: "Roles",
              render: (p) => (
                <div className="chips">
                  {p.roles.slice(0, 4).map((r) => (
                    <span className="chip" key={r.role}>{r.role} · {r.count}</span>
                  ))}
                </div>
              ),
            },
            {
              key: "go", header: "",
              render: (p) => <Link className="btn small ghost" to={`/admin/${p.slug}/analytics`}>Open</Link>,
            },
          ]}
        />
      </div>

      <div className="viz-grid two">
        <ChartCard
          title="Plan mix"
          subtitle="Subscriptions per plan across every platform. Past seven plans the tail folds into one row rather than inventing colours nobody can tell apart."
          table={{
            columns: ["Platform", "Plan", "Subscriptions"],
            rows: data.plan_mix.map((p) => [p.platform, p.plan, p.count]),
          }}
        >
          <StackedBar
            parts={foldToSlots(
              data.plan_mix,
              (p) => p.count,
              (p) => `${p.platform}:${p.plan}`,
            )}
          />
        </ChartCard>

        <ChartCard title="Members by platform" subtitle="Share of every membership in the estate.">
          <StackedBar parts={foldToSlots(data.platforms, (p) => p.members, (p) => p.name)} />
        </ChartCard>
      </div>
    </section>
  );
}

export function InsightPanel({ insights }: { insights: Insight[] }) {
  return (
    <section className="insights">
      <header>
        <h2>What the numbers say</h2>
        <p className="muted">
          Derived from the window above. Each reading carries the figures behind it, so you can
          disagree with it on the evidence.
        </p>
      </header>
      <div className="insight-list">
        {insights.map((i) => (
          <article className={`insight sev-${i.severity}`} key={i.id}>
            <span className="ins-mark" aria-hidden="true" />
            <div className="ins-body">
              <h3>
                <span className="ins-sev">{i.severity === "good" ? "clear" : i.severity}</span>
                {i.title}
              </h3>
              <p>{i.detail}</p>
            </div>
            {i.href && <Link className="btn small ghost" to={i.href}>{i.action ?? "Open"}</Link>}
          </article>
        ))}
      </div>
    </section>
  );
}
