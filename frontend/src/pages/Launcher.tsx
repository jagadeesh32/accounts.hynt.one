import { useEffect, useState } from "react";
import { api, type PlatformTile } from "../api";

export function LauncherPage() {
  const [tiles, setTiles] = useState<PlatformTile[] | null>(null);

  useEffect(() => {
    void api.get<{ platforms: PlatformTile[] }>("/api/v1/me/platforms").then((d) => setTiles(d.platforms));
  }, []);

  if (!tiles) return <div className="spinner" />;

  return (
    <section className="page">
      <header className="page-head">
        <h1>Your platforms</h1>
        <p className="muted">Open any of these — you are already signed in.</p>
      </header>

      <div className="tiles">
        {tiles.map((tile) => (
          <a
            key={tile.slug}
            className={`tile ${tile.member ? "" : "locked"}`}
            href={tile.member ? tile.url : undefined}
            // A tile you cannot open must not look like a link that failed.
            onClick={(e) => { if (!tile.member) e.preventDefault(); }}
          >
            <div className="tile-icon">{tile.icon || "◆"}</div>
            <div className="tile-body">
              <h2>{tile.name}</h2>
              <p className="muted">{tile.description}</p>
              {tile.member ? (
                <div className="chips">
                  <span className="chip role">{tile.role}</span>
                  {tile.plan && (
                    <span className={`chip plan ${tile.plan_status === "active" ? "" : "warn"}`}>
                      {tile.plan}{tile.plan_status !== "active" ? ` · ${tile.plan_status}` : ""}
                    </span>
                  )}
                </div>
              ) : (
                <div className="chips"><span className="chip muted-chip">No access</span></div>
              )}
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
