/** What the account is subscribed to on each platform, and what else is on offer. */
import { useEffect, useState } from "react";
import { api, type Plan } from "../lib/api";
import { useSession } from "../lib/session";
import { Badge, Empty, Spinner, formatDate, formatPrice } from "../components/ui";

export default function Subscriptions() {
  const { access } = useSession();
  const [plansBySlug, setPlansBySlug] = useState<Record<string, Plan[]>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const entries = await Promise.all(
        access.map(async (entry) => {
          try {
            const result = await api.publicPlans(entry.platform.slug);
            return [entry.platform.slug, result.plans] as const;
          } catch {
            return [entry.platform.slug, [] as Plan[]] as const;
          }
        }),
      );
      if (!cancelled) {
        setPlansBySlug(Object.fromEntries(entries));
        setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [access]);

  if (access.length === 0) {
    return (
      <div className="content">
        <h1 className="page-title">Plans</h1>
        <div className="card"><Empty>No platforms to show yet.</Empty></div>
      </div>
    );
  }

  return (
    <div className="content">
      <h1 className="page-title">Plans &amp; billing</h1>
      <p className="page-sub">Each platform is billed on its own plan.</p>

      {loading ? (
        <div className="card"><Empty><Spinner /></Empty></div>
      ) : (
        access.map((entry) => {
          const plans = plansBySlug[entry.platform.slug] ?? [];
          const currentCode = entry.subscription?.plan.code;
          return (
            <div className="card" key={entry.platform.id}>
              <div className="card-head">
                <div>
                  <h2 className="card-title">{entry.platform.name}</h2>
                  <p className="card-sub">
                    {entry.subscription ? (
                      <>
                        On <strong>{entry.subscription.plan.name}</strong>
                        {entry.subscription.current_period_end
                          ? ` — renews ${formatDate(entry.subscription.current_period_end)}`
                          : ""}
                      </>
                    ) : (
                      "No subscription on this platform."
                    )}
                  </p>
                </div>
                {entry.subscription ? (
                  <Badge kind={entry.subscription.status}>{entry.subscription.status}</Badge>
                ) : null}
              </div>

              <div className="grid grid-plans">
                {plans.map((plan) => (
                  <div className={`plan${plan.code === currentCode ? " current" : ""}`} key={plan.id}>
                    <div className="row-between">
                      <strong>{plan.name}</strong>
                      {plan.code === currentCode ? <Badge kind="active">current</Badge> : null}
                    </div>
                    <div className="plan-price">
                      {formatPrice(plan.price_cents, plan.currency)}
                      {plan.price_cents > 0 ? <small> / {plan.interval}</small> : null}
                    </div>
                    <p className="faint" style={{ margin: 0 }}>{plan.description}</p>
                    <ul className="plan-features">
                      {plan.features.map((feature) => (
                        <li key={feature}>{feature}</li>
                      ))}
                    </ul>
                    {plan.trial_days > 0 && plan.code !== currentCode ? (
                      <div className="faint">{plan.trial_days}-day free trial</div>
                    ) : null}
                  </div>
                ))}
              </div>

              <p className="faint" style={{ marginTop: 12 }}>
                To change plan, contact an administrator — self-serve checkout is not enabled yet.
              </p>
            </div>
          );
        })
      )}
    </div>
  );
}
