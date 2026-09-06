/**
 * One platform's analytics, for the people who administer that platform.
 *
 * Deliberately narrower than the estate board: a platform admin can see their
 * own members, roles, plans and revenue, and nothing about the estate around
 * them. The endpoint enforces that on rank; this page simply does not ask for
 * anything else.
 */
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import {
  BarList, ChartCard, SERIES, StackedBar, StatTile, TimeSeries, fmtInr, foldToSlots,
} from "../charts";
import { Segmented, relTime, type SegOption } from "../ui";
import { DataTable } from "../widgets/DataTable";
import { InsightPanel } from "./estate/Analytics";
import { change, platformInsights, sum, values, type PlatformPayload } from "../lib/insights";

type Window = "7" | "30" | "90" | "365";

const WINDOWS: SegOption<Window>[] = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
];

export function PlatformAnalyticsPage() {
  const { slug = "" } = useParams();
  const [days, setDays] = useState<Window>("30");
  const [data, setData] = useState<PlatformPayload | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api.get<PlatformPayload>(`/api/v1/admin/${slug}/analytics?days=${days}`));
      setFailed(null);
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "Could not load analytics");
    } finally {
      setBusy(false);
    }
  }, [slug, days]);

  useEffect(() => { void load(); }, [load]);

  if (!data) {
    return (
      <section className="page">
        <header className="page-head"><h1>Analytics</h1><p className="muted">Reading {slug}…</p></header>
        {failed && <div className="alert error">{failed}</div>}
      </section>
    );
  }

  const t = data.totals;
  const joined = sum(data.series.joined);
  const atRiskValue = data.at_risk.reduce((s, r) => s + r.price_inr, 0);

  return (
    <section className={`page analytics ${busy ? "reloading" : ""}`}>
      <header className="page-head">
        <div className="head-row">
          <div>
            <h1>{data.platform.name}</h1>
            <p className="muted">Members, roles, plans and revenue on this platform alone.</p>
          </div>
          <Segmented options={WINDOWS} value={days} onChange={setDays} />
        </div>
      </header>

      {failed && <div className="alert error">{failed}</div>}

      <div className="kpi-row">
        <StatTile
          label="Members" value={t.members}
          delta={change(joined, data.previous.joined)} deltaLabel={`vs previous ${data.window_days}d`}
          trend={values(data.series.joined)}
        />
        <StatTile label="Joined" value={joined} hint={`in ${data.window_days} days`} trend={values(data.series.joined)} />
        <StatTile label="Paying" value={t.paying} hint={`of ${t.members} members`} />
        <StatTile label="Monthly revenue" value={fmtInr(t.mrr_inr)} hint="active subscriptions, normalised to a month" />
        <StatTile
          label="At risk" value={t.at_risk} upIsGood={false}
          hint={atRiskValue ? `${fmtInr(atRiskValue)} a month` : "paying but dormant"}
          tone={t.at_risk > 0 ? "warning" : undefined}
        />
        <StatTile
          label="Two-factor" value={`${t.members ? Math.round((t.mfa_enabled / t.members) * 100) : 0}%`}
          hint={`${t.mfa_enabled} of ${t.members} members`}
        />
      </div>

      <InsightPanel insights={platformInsights(data)} />

      <div className="viz-grid">
        <ChartCard
          title="Members joining"
          subtitle="New memberships per day on this platform."
          table={{ columns: ["Day", "Joined"], rows: data.series.joined.map((p) => [p.d, p.v]) }}
        >
          <TimeSeries
            data={data.series.joined}
            series={[{ key: "v", label: "Joined", color: SERIES[0] }]}
            area
          />
        </ChartCard>

        <ChartCard title="Last seen" subtitle="How recently each member signed in anywhere in the estate.">
          <StackedBar
            parts={[
              { label: "Today", value: data.recency.day, color: SERIES[0] },
              { label: "This week", value: data.recency.week, color: SERIES[2] },
              { label: "This month", value: data.recency.month, color: SERIES[3] },
              { label: "Older", value: data.recency.quarter, color: SERIES[1] },
              { label: "Never", value: data.recency.never, color: "var(--panel-3)" },
            ]}
            total={data.recency.total}
          />
        </ChartCard>
      </div>

      <div className="viz-grid two">
        <ChartCard
          title="Roles"
          subtitle="Who holds what on this platform."
          table={{ columns: ["Role", "Members"], rows: data.roles.map((r) => [r.role, r.count]) }}
        >
          <BarList rows={data.roles.map((r) => ({ label: r.role, value: r.count }))} />
        </ChartCard>

        <ChartCard
          title="Plan mix"
          subtitle="Members per plan, including those holding a role with no subscription at all."
          table={{
            columns: ["Plan", "Members", "Price (₹/mo)"],
            rows: data.plans.map((p) => [p.plan, p.count, p.price_inr]),
          }}
        >
          <StackedBar parts={foldToSlots(data.plans, (p) => p.count, (p) => p.plan)} />
        </ChartCard>
      </div>

      {data.at_risk.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h2>Paying, but not signing in</h2>
            <p className="muted small-text">
              Active subscriptions on accounts that have not signed in for 30 days — the renewals
              most likely to lapse, largest first.
            </p>
          </div>
          <DataTable
            id={`at-risk-${slug}`}
            rows={data.at_risk}
            getKey={(r) => r.email}
            initialSort="price"
            exportName={`hynt-${slug}-at-risk`}
            searchPlaceholder="Search members"
            facets={[{ key: "plan", label: "Plan", of: (r) => r.plan }]}
            columns={[
              { key: "email", header: "Member", value: (r) => r.email },
              { key: "plan", header: "Plan", value: (r) => r.plan, render: (r) => <span className="chip">{r.plan}</span> },
              { key: "price", header: "₹ / month", value: (r) => r.price_inr, align: "right", render: (r) => fmtInr(r.price_inr) },
              {
                key: "seen", header: "Last sign-in", align: "right",
                value: (r) => r.last_login_at ?? "",
                render: (r) => <span className="muted">{relTime(r.last_login_at)}</span>,
              },
            ]}
          />
        </div>
      )}
    </section>
  );
}
