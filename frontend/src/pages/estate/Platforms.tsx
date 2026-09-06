import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { NoteBanner, useNote } from "../../lib/useNote";
import { Drawer, Field } from "../../widgets/Drawer";

interface PlatformRow {
  id: string; slug: string; name: string; base_url: string;
  description: string; icon: string; is_active: boolean; members: number;
}
interface Draft {
  slug: string; name: string; base_url: string;
  description: string; icon: string; isNew: boolean;
}

const EMPTY: Draft = { slug: "", name: "", base_url: "", description: "", icon: "", isNew: true };

export function EstatePlatformsPage() {
  const [rows, setRows] = useState<PlatformRow[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const { note, act } = useNote();

  const load = useCallback(async () => {
    setRows((await api.get<{ platforms: PlatformRow[] }>("/api/v1/superadmin/platforms")).platforms);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function save() {
    if (!draft) return;
    setSaving(true);
    const ok = await act(
      () => api.put(`/api/v1/superadmin/platforms/${draft.slug}`, {
        slug: draft.slug, name: draft.name, base_url: draft.base_url,
        description: draft.description, icon: draft.icon,
      }),
      `Platform "${draft.name}" saved.`,
      load,
    );
    if (ok) setDraft(null);
    setSaving(false);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Platforms</h1>
        <p className="muted">
          A platform is the audience a token is minted for. The slug is what each desk validates
          against, so it is fixed once created — changing it would invalidate every token naming it.
        </p>
      </header>

      <NoteBanner note={note} />

      <div className="card">
        <div className="card-head">
          <h2>{rows.length} platform{rows.length === 1 ? "" : "s"}</h2>
          <button className="btn primary" onClick={() => setDraft({ ...EMPTY })}>New platform</button>
        </div>
        <table className="table">
          <thead><tr><th>Platform</th><th>URL</th><th>Members</th><th>State</th><th /></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className={p.is_active ? "" : "dim"}>
                <td>
                  <div className="who-text">
                    <span>{p.icon} {p.name}</span>
                    <span className="who-email mono">{p.slug}</span>
                  </div>
                </td>
                <td className="mono small-text">{p.base_url || "—"}</td>
                <td className="muted">{p.members}</td>
                <td><span className={`chip ${p.is_active ? "ok-chip" : "warn"}`}>{p.is_active ? "active" : "off"}</span></td>
                <td className="right">
                  <button className="btn small ghost" onClick={() => setDraft({
                    slug: p.slug, name: p.name, base_url: p.base_url,
                    description: p.description, icon: p.icon, isNew: false,
                  })}>Edit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Drawer
        open={draft !== null}
        title={draft?.isNew ? "New platform" : `Edit ${draft?.name || "platform"}`}
        onClose={() => setDraft(null)}
        onSave={() => void save()}
        busy={saving || !draft?.slug || !draft?.name}
        saveLabel={draft?.isNew ? "Create platform" : "Save platform"}
      >
        {draft && (
          <>
            <div className="dw-row">
              <Field label="Slug" hint={draft.isNew ? "Permanent. Becomes the token audience." : "Fixed once created"}>
                <input value={draft.slug} disabled={!draft.isNew}
                       onChange={(e) => setDraft({ ...draft, slug: e.target.value.trim() })} />
              </Field>
              <Field label="Icon" hint="One emoji">
                <input value={draft.icon} onChange={(e) => setDraft({ ...draft, icon: e.target.value })} />
              </Field>
            </div>
            <Field label="Name">
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Field>
            <Field label="Base URL" hint="Where the launcher tile sends people, e.g. https://terminal.hynt.one">
              <input value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} />
            </Field>
            <Field label="Description" hint="Shown under the tile on the launcher">
              <input value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </Field>
          </>
        )}
      </Drawer>
    </section>
  );
}
