import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { StatTile } from "../../charts";
import { NoteBanner, useNote } from "../../lib/useNote";
import { DataTable } from "../../widgets/DataTable";

interface KeyRow { kid: string; is_active: boolean; created_at: string; retired_at: string | null }

export function KeysPage() {
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const { note, act } = useNote();

  const load = useCallback(async () => {
    setKeys((await api.get<{ keys: KeyRow[] }>("/api/v1/superadmin/keys")).keys);
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Age of the key currently signing tokens. Rotation is a calendar habit, and
  // the only way to keep it is to be told the number without asking for it.
  const active = useMemo(() => keys.find((k) => k.is_active) ?? null, [keys]);
  const ageDays = active ? Math.floor((Date.now() - new Date(active.created_at).getTime()) / 86400e3) : null;

  return (
    <section className="page">
      <header className="page-head">
        <h1>Signing keys</h1>
        <p className="muted">
          The RS256 keys behind every access token. Desks verify against the published JWKS and
          cache it for an hour, so a new key is not universally known the instant it exists.
        </p>
      </header>

      <NoteBanner note={note} />

      <div className="card">
        <div className="card-head">
          <h2>{keys.length} key{keys.length === 1 ? "" : "s"}</h2>
          <button className="btn primary" onClick={() => {
            if (!window.confirm("Rotate the signing key? New tokens use the new key immediately; the old one stays published until the last token it signed expires.")) return;
            void act(
              () => api.post("/api/v1/superadmin/keys/rotate"),
              "Rotated. Platforms pick the new key up on their next JWKS refresh — up to an hour.",
              load,
            );
          }}>Rotate</button>
        </div>
        <p className="muted">
          A retired key stays published until the last token it signed has expired, so rotating
          never signs anyone out. Rotate on a schedule, or immediately if a key is ever exposed.
        </p>
        <div className="kpi-row">
          <StatTile
            label="Active key age" value={ageDays === null ? "—" : `${ageDays}d`}
            hint={active ? active.kid : "no active key"}
            tone={ageDays !== null && ageDays > 180 ? "critical" : ageDays !== null && ageDays > 90 ? "warning" : undefined}
          />
          <StatTile label="Keys published" value={keys.length} hint="active plus retired-but-verifying" />
          <StatTile label="Retired" value={keys.filter((k) => !k.is_active).length} hint="still verifying old tokens" />
        </div>

        <DataTable
          id="estate-keys"
          rows={keys}
          getKey={(k) => k.kid}
          initialSort="created"
          exportName="hynt-signing-keys"
          searchPlaceholder="Search key id"
          facets={[{ key: "state", label: "State", of: (k) => (k.is_active ? "active" : "retired") }]}
          columns={[
            { key: "kid", header: "Key id", value: (k) => k.kid, render: (k) => <span className="mono">{k.kid}</span> },
            {
              key: "state", header: "State", value: (k) => (k.is_active ? "active" : "retired"),
              render: (k) => <span className={`chip ${k.is_active ? "ok-chip" : ""}`}>{k.is_active ? "active" : "retired"}</span>,
            },
            {
              key: "created", header: "Created", value: (k) => k.created_at,
              render: (k) => <span className="muted">{new Date(k.created_at).toLocaleString()}</span>,
            },
            {
              key: "retired", header: "Retired", value: (k) => k.retired_at ?? "",
              render: (k) => <span className="muted">{k.retired_at ? new Date(k.retired_at).toLocaleString() : "—"}</span>,
            },
          ]}
        />
      </div>
    </section>
  );
}
