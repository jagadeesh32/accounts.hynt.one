import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { NoteBanner, useNote } from "../../lib/useNote";

interface KeyRow { kid: string; is_active: boolean; created_at: string; retired_at: string | null }

export function KeysPage() {
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const { note, act } = useNote();

  const load = useCallback(async () => {
    setKeys((await api.get<{ keys: KeyRow[] }>("/api/v1/superadmin/keys")).keys);
  }, []);

  useEffect(() => { void load(); }, [load]);

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
        <table className="table">
          <thead><tr><th>Key id</th><th>State</th><th>Created</th><th>Retired</th></tr></thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.kid}>
                <td className="mono">{k.kid}</td>
                <td><span className={`chip ${k.is_active ? "ok-chip" : ""}`}>{k.is_active ? "active" : "retired"}</span></td>
                <td className="muted">{new Date(k.created_at).toLocaleString()}</td>
                <td className="muted">{k.retired_at ? new Date(k.retired_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
