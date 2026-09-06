/**
 * The reading layer — what the numbers on the analytics board actually say.
 *
 * Every finding here is arithmetic you could redo by hand from the same
 * payload, and each one carries the figures it was derived from. That is the
 * whole design rule: a panel that asserts "unusual activity" without showing
 * the count, the baseline and the threshold is not intelligence, it is a mood.
 *
 * Two guards keep this honest on a small estate, where most of these ratios are
 * noise:
 *   · MIN_N — a percentage of four events is not a trend, so findings that rest
 *     on a rate carry a floor on the count behind it.
 *   · Spread — the anomaly test needs a baseline that actually varies; on a
 *     series that is flat at zero, one event is infinitely many standard
 *     deviations from the mean and means nothing.
 */

export type Severity = "critical" | "warning" | "info" | "good";

export interface Insight {
  id: string;
  severity: Severity;
  title: string;
  /** The arithmetic, in words, including the numbers it used. */
  detail: string;
  /** Optional deep link — the page that lets you act on it. */
  href?: string;
  action?: string;
}

const RANK: Record<Severity, number> = { critical: 0, warning: 1, info: 2, good: 3 };

/** A finding built on a rate needs at least this many events underneath it. */
const MIN_N = 8;

export interface Point { d: string; v: number }

export function sum(points: Point[]): number {
  return points.reduce((a, p) => a + p.v, 0);
}

export function values(points: Point[]): number[] {
  return points.map((p) => p.v);
}

/** Fractional change, or null when the baseline is too small to divide by. */
export function change(now: number, before: number): number | null {
  if (before <= 0) return now > 0 ? null : 0;
  return (now - before) / before;
}

/** Mean and population standard deviation. */
function stats(xs: number[]): { mean: number; sd: number } {
  if (!xs.length) return { mean: 0, sd: 0 };
  const mean = xs.reduce((a, x) => a + x, 0) / xs.length;
  const variance = xs.reduce((a, x) => a + (x - mean) ** 2, 0) / xs.length;
  return { mean, sd: Math.sqrt(variance) };
}

/**
 * Days more than `z` standard deviations above the mean of the days before
 * them. Compared against the series' OWN history rather than a fixed number,
 * because "40 failed sign-ins" is a quiet morning on one estate and an
 * emergency on another.
 */
export function spikes(points: Point[], z = 2.5): Point[] {
  if (points.length < 7) return [];
  const { mean, sd } = stats(values(points));
  if (sd < 1) return [];                       // a flat series has no anomalies
  return points.filter((p) => p.v > mean + z * sd && p.v >= 3);
}

export interface EstatePayload {
  window_days: number;
  totals: {
    users: number; active_users: number; suspended: number; mfa_enabled: number;
    superadmins: number; superadmins_without_mfa: number; platforms: number;
    memberships: number; subscriptions: number; clients: number; live_sessions: number; mrr_inr: number;
  };
  series: { signups: Point[]; logins: Point[]; failures: Point[]; admin_actions: Point[]; active_users: Point[] };
  previous: { signups: number; logins: number; failures: number; active_users: number; admin_actions: number };
  recency: { day: number; week: number; month: number; quarter: number; never: number; total: number };
  failure_sources: { ip: string; count: number; accounts: number }[];
  platforms: {
    slug: string; name: string; is_active: boolean; members: number; active_30d: number;
    subscriptions: number; paying: number; mrr_inr: number;
    roles: { role: string; count: number }[]; plans: { plan: string; count: number }[];
  }[];
  top_actors: { actor: string; count: number }[];
  actions: { action: string; count: number }[];
  heatmap: { dow: number; hour: number; v: number }[];
  mfa: { enabled: number; disabled: number };
  plan_mix: { platform: string; plan: string; count: number }[];
}

export function estateInsights(a: EstatePayload): Insight[] {
  const out: Insight[] = [];
  const days = a.window_days;
  const period = `the previous ${days} days`;

  /* ── security ─────────────────────────────────────────────────────── */

  if (a.totals.superadmins_without_mfa > 0) {
    out.push({
      id: "superadmin-mfa",
      severity: "critical",
      title: `${a.totals.superadmins_without_mfa} superadmin${a.totals.superadmins_without_mfa === 1 ? "" : "s"} without two-factor`,
      detail:
        `Of ${a.totals.superadmins} superadmin account${a.totals.superadmins === 1 ? "" : "s"}, ` +
        `${a.totals.superadmins_without_mfa} sign in with a password alone. A superadmin can rotate the ` +
        `signing keys and reach every platform in the estate.`,
      href: "/estate/accounts",
      action: "Review accounts",
    });
  }

  const failures = sum(a.series.failures);
  const logins = sum(a.series.logins);
  const attempts = failures + logins;
  if (attempts >= MIN_N) {
    const rate = failures / attempts;
    if (rate > 0.3) {
      out.push({
        id: "failure-rate",
        severity: rate > 0.5 ? "critical" : "warning",
        title: `${Math.round(rate * 100)}% of sign-in attempts failed`,
        detail: `${failures.toLocaleString()} rejected against ${logins.toLocaleString()} accepted over ${days} days. Above roughly a third, this is usually either an attack or a platform holding a stale credential and retrying it.`,
        href: "/estate/audit",
        action: "Open the audit log",
      });
    }
  }

  const failureSpikes = spikes(a.series.failures);
  if (failureSpikes.length) {
    const worst = failureSpikes.reduce((a2, b) => (b.v > a2.v ? b : a2));
    const { mean } = stats(values(a.series.failures));
    out.push({
      id: "failure-spike",
      severity: "warning",
      title: `Failed sign-ins spiked on ${new Date(`${worst.d}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`,
      detail: `${worst.v} failures that day against a ${days}-day average of ${mean.toFixed(1)} — more than 2.5 standard deviations above this estate's own baseline${failureSpikes.length > 1 ? `, and ${failureSpikes.length - 1} other day${failureSpikes.length === 2 ? "" : "s"} in the window did the same` : ""}.`,
      href: "/estate/audit",
      action: "Open the audit log",
    });
  }

  const topSource = a.failure_sources[0];
  if (topSource && failures >= MIN_N && topSource.count / failures > 0.4) {
    out.push({
      id: "failure-source",
      severity: topSource.accounts >= 3 ? "critical" : "warning",
      title: `One address is behind ${Math.round((topSource.count / failures) * 100)}% of failed sign-ins`,
      detail:
        `${topSource.ip} accounts for ${topSource.count} of ${failures} failures` +
        (topSource.accounts >= 3
          ? `, against ${topSource.accounts} different accounts — that shape is someone working through a list, not a person mistyping.`
          : `, all against ${topSource.accounts} account${topSource.accounts === 1 ? "" : "s"} — most likely a stale saved password.`),
      href: "/estate/audit",
      action: "Open the audit log",
    });
  }

  const mfaRate = a.totals.users > 0 ? a.totals.mfa_enabled / a.totals.users : 1;
  if (a.totals.users >= 5 && mfaRate < 0.6) {
    out.push({
      id: "mfa-coverage",
      severity: mfaRate < 0.3 ? "warning" : "info",
      title: `Two-factor covers ${Math.round(mfaRate * 100)}% of accounts`,
      detail: `${a.totals.mfa_enabled} of ${a.totals.users} accounts have it enabled; ${a.totals.users - a.totals.mfa_enabled} rely on a password alone.`,
      href: "/estate/accounts",
      action: "Review accounts",
    });
  }

  /* ── growth and usage ─────────────────────────────────────────────── */

  const signups = sum(a.series.signups);
  const signupDelta = change(signups, a.previous.signups);
  if (signupDelta !== null && Math.abs(signupDelta) >= 0.25 && Math.max(signups, a.previous.signups) >= 4) {
    out.push({
      id: "signup-trend",
      severity: signupDelta > 0 ? "good" : "info",
      title: `New accounts ${signupDelta > 0 ? "up" : "down"} ${Math.abs(Math.round(signupDelta * 100))}%`,
      detail: `${signups} created in the last ${days} days against ${a.previous.signups} in ${period}.`,
    });
  }

  const active = a.recency.month;
  if (a.totals.users >= 10) {
    const dormantShare = 1 - active / a.totals.users;
    if (dormantShare > 0.4) {
      out.push({
        id: "dormant",
        severity: dormantShare > 0.7 ? "warning" : "info",
        title: `${Math.round(dormantShare * 100)}% of accounts have not signed in for 30 days`,
        detail: `${a.totals.users - active} of ${a.totals.users} accounts are dormant, of which ${a.recency.never} have never signed in at all — those are provisioned seats nobody has used.`,
        href: "/estate/accounts",
        action: "Review accounts",
      });
    }
  }

  const loginDelta = change(logins, a.previous.logins);
  if (loginDelta !== null && Math.abs(loginDelta) >= 0.3 && Math.max(logins, a.previous.logins) >= MIN_N) {
    out.push({
      id: "login-trend",
      severity: loginDelta > 0 ? "good" : "info",
      title: `Sign-ins ${loginDelta > 0 ? "up" : "down"} ${Math.abs(Math.round(loginDelta * 100))}%`,
      detail: `${logins.toLocaleString()} in the last ${days} days against ${a.previous.logins.toLocaleString()} in ${period}.`,
    });
  }

  /* ── shape of the estate ──────────────────────────────────────────── */

  const totalMembers = a.platforms.reduce((s, p) => s + p.members, 0);
  const biggest = [...a.platforms].sort((x, y) => y.members - x.members)[0];
  if (biggest && totalMembers >= 10 && a.platforms.length > 1 && biggest.members / totalMembers > 0.7) {
    out.push({
      id: "concentration",
      severity: "info",
      title: `${biggest.name} holds ${Math.round((biggest.members / totalMembers) * 100)}% of all memberships`,
      detail: `${biggest.members} of ${totalMembers} memberships sit on one platform, so estate-wide averages mostly describe ${biggest.name}.`,
    });
  }

  for (const p of a.platforms) {
    if (p.members >= 10 && p.active_30d / p.members < 0.25) {
      out.push({
        id: `stale-${p.slug}`,
        severity: "info",
        title: `${p.name}: ${Math.round((p.active_30d / p.members) * 100)}% of members active`,
        detail: `${p.active_30d} of ${p.members} members signed in within 30 days.`,
      });
    }
  }

  if (a.totals.suspended > 0) {
    out.push({
      id: "suspended",
      severity: "info",
      title: `${a.totals.suspended} suspended account${a.totals.suspended === 1 ? "" : "s"}`,
      detail: "Their sessions are revoked and every platform stops honouring their tokens within seconds.",
      href: "/estate/accounts",
      action: "Review accounts",
    });
  }

  if (!out.length) {
    out.push({
      id: "clear",
      severity: "good",
      title: "Nothing stands out",
      detail: `Over ${days} days: no failure spike above this estate's own baseline, no single source behind the failures there are, and two-factor coverage above 60%.`,
    });
  }

  return out.sort((x, y) => RANK[x.severity] - RANK[y.severity]);
}

export interface PlatformPayload {
  window_days: number;
  platform: { slug: string; name: string };
  totals: { members: number; suspended: number; mfa_enabled: number; paying: number; mrr_inr: number; at_risk: number };
  series: { joined: Point[] };
  previous: { joined: number };
  roles: { role: string; count: number }[];
  plans: { plan: string; count: number; price_inr: number }[];
  recency: { day: number; week: number; month: number; quarter: number; never: number; total: number };
  at_risk: { email: string; plan: string; price_inr: number; last_login_at: string | null }[];
}

export function platformInsights(a: PlatformPayload): Insight[] {
  const out: Insight[] = [];
  const days = a.window_days;

  if (a.totals.at_risk > 0) {
    const value = a.at_risk.reduce((s, r) => s + r.price_inr, 0);
    out.push({
      id: "at-risk",
      severity: a.totals.at_risk >= 5 ? "warning" : "info",
      title: `${a.totals.at_risk} paying member${a.totals.at_risk === 1 ? "" : "s"} have not signed in for 30 days`,
      detail: `Roughly ₹${value.toLocaleString()} a month of subscriptions attached to accounts nobody is using${a.at_risk.length < a.totals.at_risk ? " (the twenty largest are listed below)" : ""}.`,
    });
  }

  const joined = sum(a.series.joined);
  const delta = change(joined, a.previous.joined);
  if (delta !== null && Math.abs(delta) >= 0.25 && Math.max(joined, a.previous.joined) >= 4) {
    out.push({
      id: "joined",
      severity: delta > 0 ? "good" : "info",
      title: `New members ${delta > 0 ? "up" : "down"} ${Math.abs(Math.round(delta * 100))}%`,
      detail: `${joined} joined in the last ${days} days against ${a.previous.joined} in the ${days} before that.`,
    });
  }

  const mfaRate = a.totals.members ? a.totals.mfa_enabled / a.totals.members : 1;
  if (a.totals.members >= 5 && mfaRate < 0.6) {
    out.push({
      id: "mfa",
      severity: mfaRate < 0.3 ? "warning" : "info",
      title: `Two-factor covers ${Math.round(mfaRate * 100)}% of members`,
      detail: `${a.totals.mfa_enabled} of ${a.totals.members} members have it enabled. Two-factor is set by the account holder, not by an admin — this is a number to nudge, not to change.`,
    });
  }

  const free = a.plans.find((p) => p.plan === "none");
  if (free && a.totals.members >= 10 && free.count / a.totals.members > 0.5) {
    out.push({
      id: "unsubscribed",
      severity: "info",
      title: `${Math.round((free.count / a.totals.members) * 100)}% of members have no subscription`,
      detail: `${free.count} of ${a.totals.members} members hold a role but no plan, so they get role access with no entitlements attached.`,
    });
  }

  const engaged = a.recency.day + a.recency.week + a.recency.month;
  if (a.totals.members >= 10 && engaged / a.totals.members < 0.4) {
    out.push({
      id: "engagement",
      severity: "info",
      title: `${Math.round((engaged / a.totals.members) * 100)}% of members signed in this month`,
      detail: `${engaged} of ${a.totals.members}, of which ${a.recency.never} have never signed in.`,
    });
  }

  if (!out.length) {
    out.push({
      id: "clear",
      severity: "good",
      title: "Nothing stands out",
      detail: "No lapsed paying members, no unusual change in joins, and two-factor coverage above 60%.",
    });
  }

  return out.sort((x, y) => RANK[x.severity] - RANK[y.severity]);
}
