import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { NoteBanner, useNote } from "../lib/useNote";
import { Drawer, Field, JsonField, ListField } from "../widgets/Drawer";

interface PlanRow {
  slug: string; name: string; price_inr: number; is_default: boolean;
  interval: string; entitlements: string[]; limits: Record<string, unknown>;
}
interface Member { plan: string | null }

/** The draft behind the drawer. `limitsText` stays raw text rather than a parsed
 *  object so a half-typed JSON object does not fight the cursor. */
interface PlanDraft {
  slug: string; name: string; price_inr: number; interval: string;
  entitlements: string[]; limitsText: string; is_default: boolean; isNew: boolean;
}

const EMPTY: PlanDraft = {
  slug: "", name: "", price_inr: 0, interval: "month",
  entitlements: [], limitsText: "{}", is_default: false, isNew: true,
};

export function PlansPage() {
  const { slug = "" } = useParams();
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const [limitsOk, setLimitsOk] = useState(true);
  const [saving, setSaving] = useState(false);
  const { note, setNote, act } = useNote();

  const load = useCallback(async () => {
    if (!slug) return;
    const [p, m] = await Promise.all([
      api.get<{ plans: PlanRow[] }>(`/api/v1/admin/${slug}/plans`),
      api.get<{ members: Member[] }>(`/api/v1/admin/${slug}/members`),
    ]);
    setPlans(p.plans);
    setMembers(m.members);
  }, [slug]);

  useEffect(() => { void load(); }, [load]);

  async function savePlan() {
    if (!draft) return;
    setSaving(true);
    setNote(null);
    // The drawer stays open on failure: closing discards the draft and makes
    // someone retype everything to find out what the server disliked.
    try {
      await api.put(`/api/v1/admin/${slug}/plans/${draft.slug}`, {
        slug: draft.slug,
        name: draft.name,
        price_inr: Number(draft.price_inr) || 0,
        interval: draft.interval,
        entitlements: draft.entitlements,
        limits: JSON.parse(draft.limitsText || "{}"),
        is_default: draft.is_default,
      });
      setDraft(null);
      setNote({ kind: "ok", text: `Plan "${draft.name}" saved. Members pick it up on their next token — up to 15 minutes.` });
      await load();
    } catch (err) {
      setNote({ kind: "error", text: err instanceof ApiError ? err.message : "Could not save the plan." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Plans</h1>
        <p className="muted">
          What a subscription on <span className="mono">{slug}</span> grants. Entitlements and
          limits are copied into every access token, so an edit reaches each desk on the member's
          next token — within 15 minutes.
        </p>
      </header>

      <NoteBanner note={note} />

      <div className="card">
        <div className="card-head">
          <h2>{plans.length} plan{plans.length === 1 ? "" : "s"}</h2>
          <button className="btn primary" onClick={() => setDraft({ ...EMPTY })}>New plan</button>
        </div>
        <table className="table">
          <thead>
            <tr><th>Plan</th><th>Price</th><th>Entitlements</th><th>Limits</th><th>Members</th><th /></tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.slug}>
                <td>
                  <div className="who-text">
                    <span>{p.name}{p.is_default && <span className="chip small">default</span>}</span>
                    <span className="who-email mono">{p.slug}</span>
                  </div>
                </td>
                <td>{p.price_inr ? `₹${p.price_inr.toLocaleString("en-IN")}/${p.interval}` : "Free"}</td>
                <td>
                  <div className="chips">
                    {p.entitlements.map((e) => <span key={e} className="chip small">{e}</span>)}
                    {!p.entitlements.length && <span className="muted">—</span>}
                  </div>
                </td>
                <td className="mono small-text">
                  {Object.keys(p.limits ?? {}).length
                    ? Object.entries(p.limits).map(([k, v]) => `${k}: ${String(v)}`).join("\n")
                    : "—"}
                </td>
                <td className="muted">{members.filter((m) => m.plan === p.slug).length}</td>
                <td className="right">
                  <button className="btn small ghost" onClick={() => setDraft({
                    slug: p.slug, name: p.name, price_inr: p.price_inr, interval: p.interval,
                    entitlements: p.entitlements ?? [],
                    limitsText: JSON.stringify(p.limits ?? {}, null, 2),
                    is_default: p.is_default, isNew: false,
                  })}>Edit</button>
                </td>
              </tr>
            ))}
            {!plans.length && <tr><td colSpan={6} className="muted">No plans on this platform yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <Drawer
        open={draft !== null}
        title={draft?.isNew ? "New plan" : `Edit ${draft?.name || "plan"}`}
        subtitle={`On ${slug}`}
        onClose={() => setDraft(null)}
        onSave={() => void savePlan()}
        busy={saving || !limitsOk || !draft?.slug || !draft?.name}
        saveLabel={draft?.isNew ? "Create plan" : "Save plan"}
      >
        {draft && (
          <>
            <div className="dw-row">
              <Field label="Slug" hint={draft.isNew ? "Permanent id, e.g. pro" : "Cannot be changed"}>
                <input value={draft.slug} disabled={!draft.isNew}
                       onChange={(e) => setDraft({ ...draft, slug: e.target.value.trim() })} />
              </Field>
              <Field label="Name" hint="What members see">
                <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </Field>
            </div>

            <div className="dw-row">
              <Field label="Price (INR)" hint="0 for free">
                <input type="number" min={0} value={draft.price_inr}
                       onChange={(e) => setDraft({ ...draft, price_inr: Number(e.target.value) })} />
              </Field>
              <Field label="Interval">
                <select value={draft.interval} onChange={(e) => setDraft({ ...draft, interval: e.target.value })}>
                  <option value="month">Monthly</option>
                  <option value="year">Yearly</option>
                  <option value="once">One-off</option>
                </select>
              </Field>
            </div>

            <ListField
              label="Entitlements"
              hint="One per line. Becomes the token's `ent` claim; a desk checks it with hasEntitlement()."
              value={draft.entitlements}
              onChange={(entitlements) => setDraft({ ...draft, entitlements })}
              placeholder={"terminal.eod\nterminal.intraday"}
            />

            <JsonField
              label="Limits"
              hint={"A JSON object, e.g. {\"alerts\": 200}. Read by planLimit() on each desk, which has to enforce it."}
              text={draft.limitsText}
              onText={(limitsText) => setDraft({ ...draft, limitsText })}
              onValidity={setLimitsOk}
            />

            <label className="dw-check">
              <input type="checkbox" checked={draft.is_default}
                     onChange={(e) => setDraft({ ...draft, is_default: e.target.checked })} />
              <span>Default for new members{draft.is_default ? " — this clears the flag on the others" : ""}</span>
            </label>
          </>
        )}
      </Drawer>
    </section>
  );
}
