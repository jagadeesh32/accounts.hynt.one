import { useEffect, useState } from "react";
import { api, type Me, type PlatformTile } from "../api";
import { Avatar, Icon, Skeleton } from "../ui";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Working late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function LauncherPage({ me }: { me: Me }) {
  const [tiles, setTiles] = useState<PlatformTile[] | null>(null);

  useEffect(() => {
    void api.get<{ platforms: PlatformTile[] }>("/api/v1/me/platforms").then((d) => setTiles(d.platforms));
  }, []);

  const unlocked = tiles?.filter((t) => t.member).length ?? 0;
  const firstName = (me.full_name || me.email).split(/[\s@]/)[0];

  return (
    <section className="page">
      <div className="hero">
        <Avatar name={me.full_name} email={me.email} size="lg" />
        <div className="hero-body">
          <div className="hero-kicker">{greeting()}, {firstName}</div>
          <h1>Your platforms</h1>
          <p className="sub">
            Open any of these — you are already signed in.
            {tiles && ` ${unlocked} of ${tiles.length} available to you.`}
          </p>
        </div>
        <div className="chips">
          <span className="chip ok-chip"><span className="dot" />SSO session active</span>
          {me.mfa_enabled && <span className="chip accent-chip"><Icon name="shield-check" size={11} />2FA on</span>}
        </div>
      </div>

      {!tiles ? (
        <div className="tiles" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="tile">
              <Skeleton w={46} h={46} style={{ borderRadius: 13 }} />
              <div style={{ flex: 1 }}>
                <Skeleton w="55%" h={15} />
                <div style={{ height: 7 }} />
                <Skeleton w="90%" h={11} />
                <div style={{ height: 9 }} />
                <Skeleton w="35%" h={17} style={{ borderRadius: 20 }} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="tiles">
          {tiles.map((tile, i) => (
            <a
              key={tile.slug}
              className={`tile ${tile.member ? "" : "locked"}`}
              href={tile.member ? tile.url : undefined}
              style={{ animationDelay: `${i * 60}ms` }}
              // A tile you cannot open must not look like a link that failed.
              onClick={(e) => { if (!tile.member) e.preventDefault(); }}
              onMouseMove={(e) => {
                const r = e.currentTarget.getBoundingClientRect();
                e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
                e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
              }}
            >
              <div className="tile-icon">{tile.icon || "◆"}</div>
              <div className="tile-body">
                <h2>{tile.name}</h2>
                <p>{tile.description}</p>
                {tile.member ? (
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <div className="chips">
                      <span className="chip role"><span className="dot" />{tile.role}</span>
                      {tile.plan && (
                        <span className={`chip ${tile.plan_status === "active" ? "ok-chip" : "warn"}`}>
                          {tile.plan}{tile.plan_status !== "active" ? ` · ${tile.plan_status}` : ""}
                        </span>
                      )}
                    </div>
                    <span className="open-aff">Open <Icon name="arrow-up-right" size={13} /></span>
                  </div>
                ) : (
                  <span className="lock-aff">
                    <Icon name="lock" size={12} /> No access — ask an admin
                  </span>
                )}
              </div>
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
