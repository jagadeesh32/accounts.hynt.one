import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { NoteBanner, useNote } from "../../lib/useNote";
import { Drawer, Field, ListField } from "../../widgets/Drawer";
import { DataTable } from "../../widgets/DataTable";

interface ClientRow {
  client_id: string; name: string; platform: string;
  redirect_uris: string[]; is_public?: boolean; is_active: boolean;
}
interface PlatformRow { slug: string; name: string }
interface Draft {
  client_id: string; name: string; platform: string;
  redirect_uris: string[]; is_public: boolean; isNew: boolean;
}

export function ClientsPage() {
  const [rows, setRows] = useState<ClientRow[]>([]);
  const [platforms, setPlatforms] = useState<PlatformRow[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const { note, act } = useNote();

  const load = useCallback(async () => {
    const [c, p] = await Promise.all([
      api.get<{ clients: ClientRow[] }>("/api/v1/superadmin/clients"),
      api.get<{ platforms: PlatformRow[] }>("/api/v1/superadmin/platforms"),
    ]);
    setRows(c.clients);
    setPlatforms(p.platforms);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function save() {
    if (!draft) return;
    setSaving(true);
    const ok = await act(
      () => api.put(`/api/v1/superadmin/clients/${draft.client_id}`, {
        client_id: draft.client_id, name: draft.name, platform: draft.platform,
        redirect_uris: draft.redirect_uris, is_public: draft.is_public,
      }),
      `Client "${draft.client_id}" saved.`,
      load,
    );
    if (ok) setDraft(null);
    setSaving(false);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>OAuth clients</h1>
        <p className="muted">
          One public, PKCE-only client per platform SPA. The redirect URI allow-list is matched
          exactly — an unexplained <span className="mono">redirect_uri is not registered</span> at
          /oauth/authorize is this list.
        </p>
      </header>

      <NoteBanner note={note} />

      <div className="card">
        <div className="card-head">
          <h2>OAuth clients</h2>
          <button
            className="btn primary"
            onClick={() => setDraft({
              client_id: "", name: "", platform: platforms[0]?.slug ?? "",
              redirect_uris: [], is_public: true, isNew: true,
            })}
          >
            New client
          </button>
        </div>
        <DataTable
          id="estate-clients"
          rows={rows}
          getKey={(c) => c.client_id}
          initialSort="client"
          initialDir="asc"
          exportName="hynt-oauth-clients"
          searchPlaceholder="Search client id, name or URI"
          facets={[
            { key: "platform", label: "Platform", of: (c) => c.platform },
            { key: "kind", label: "Kind", of: (c) => (c.is_public ? "public (PKCE)" : "confidential") },
          ]}
          columns={[
            {
              key: "client", header: "Client", value: (c) => `${c.client_id} ${c.name}`,
              render: (c) => (
                <div className="who-text">
                  <span className="mono">{c.client_id}</span>
                  <span className="who-email">{c.name}</span>
                </div>
              ),
            },
            { key: "platform", header: "Platform", value: (c) => c.platform },
            {
              key: "kind", header: "Kind", value: (c) => (c.is_public ? "public" : "confidential"),
              render: (c) => <span className="chip">{c.is_public ? "public · PKCE" : "confidential"}</span>,
            },
            {
              key: "uris", header: "Redirect URIs",
              value: (c) => c.redirect_uris.join(" "),
              render: (c) => <span className="mono small-text">{c.redirect_uris.join("\n")}</span>,
            },
            {
              key: "state", header: "State", value: (c) => (c.is_active ? "active" : "off"),
              render: (c) => <span className={`chip ${c.is_active ? "ok-chip" : "warn"}`}>{c.is_active ? "active" : "off"}</span>,
            },
            {
              key: "edit", header: "", align: "right",
              render: (c) => (
                <button className="btn small ghost" onClick={() => setDraft({
                  client_id: c.client_id, name: c.name, platform: c.platform,
                  redirect_uris: c.redirect_uris, is_public: c.is_public ?? true, isNew: false,
                })}>Edit</button>
              ),
            },
          ]}
        />
      </div>

      <Drawer
        open={draft !== null}
        title={draft?.isNew ? "New OAuth client" : `Edit ${draft?.client_id || "client"}`}
        onClose={() => setDraft(null)}
        onSave={() => void save()}
        busy={saving || !draft?.client_id || !draft?.platform || !draft?.redirect_uris.length}
        saveLabel={draft?.isNew ? "Create client" : "Save client"}
      >
        {draft && (
          <>
            <div className="dw-row">
              <Field label="Client id" hint={draft.isNew ? "e.g. terminal-web" : "Fixed once created"}>
                <input value={draft.client_id} disabled={!draft.isNew}
                       onChange={(e) => setDraft({ ...draft, client_id: e.target.value.trim() })} />
              </Field>
              <Field label="Platform">
                <select value={draft.platform} onChange={(e) => setDraft({ ...draft, platform: e.target.value })}>
                  {platforms.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
                </select>
              </Field>
            </div>
            <Field label="Name">
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Field>
            <ListField
              label="Redirect URIs"
              hint="One per line, matched exactly. Include a dev origin too if you run one against production."
              value={draft.redirect_uris}
              onChange={(redirect_uris) => setDraft({ ...draft, redirect_uris })}
              rows={5}
              placeholder={"https://terminal.hynt.one/auth/callback\nhttp://localhost:5173/auth/callback"}
            />
            <label className="dw-check">
              <input type="checkbox" checked={draft.is_public}
                     onChange={(e) => setDraft({ ...draft, is_public: e.target.checked })} />
              <span>Public client (PKCE, no secret) — correct for every browser SPA</span>
            </label>
          </>
        )}
      </Drawer>
    </section>
  );
}
