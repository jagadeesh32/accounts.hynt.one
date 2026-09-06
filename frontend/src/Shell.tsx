/**
 * The console frame: a collapsible nav rail, a top bar, and the routed page.
 *
 * Same shape as terminal.hynt.one — grid areas "side top" / "side main" — but
 * built on this app's own tokens rather than Terminal's glass ones, so all
 * seventeen palettes in styles/themes.css keep working without edits there.
 *
 * The rail is built from what you may actually reach: an admin sees only the
 * platforms they administer, and Estate appears only for a superadmin. Hiding a
 * link you cannot use is not security — the API enforces that — it is what stops
 * the rail reading as a list of things that are broken.
 */
import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import type { Me } from "./api";
import { AppearanceButton } from "./widgets/AppearancePanel";

const COLLAPSE_KEY = "hynt.accounts.rail.collapsed";

export interface AdminPlatform { slug: string; name: string; your_rank: number }

interface NavItem { to: string; label: string; icon: string; end?: boolean }
interface NavGroup { label: string; items: NavItem[] }

export function Shell({
  me,
  platforms,
  onSignOut,
}: {
  me: Me;
  platforms: AdminPlatform[];
  onSignOut: () => void;
}) {
  // Two independent states, because the rail means different things by width.
  // Wide: collapsed shrinks it to an icon strip and is remembered. Narrow: it is
  // hidden entirely and `railOpen` slides it over the page for one navigation.
  const [railOpen, setRailOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      // Storage can throw outright in a locked-down browser, not just return
      // null — an expanded rail is the safe default either way.
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* a rail that forgets its width is not worth failing over */
    }
  }, [collapsed]);

  const groups = useMemo<NavGroup[]>(() => {
    const out: NavGroup[] = [
      {
        label: "Workspace",
        items: [
          { to: "/", label: "Platforms", icon: "◧", end: true },
          { to: "/security", label: "Security", icon: "⛨" },
        ],
      },
    ];

    if (platforms.length) {
      out.push({
        label: platforms.length === 1 ? "Administration" : "Administer",
        items: platforms.flatMap((p) => [
          { to: `/admin/${p.slug}/members`, label: `${p.name} · Members`, icon: "◔" },
          { to: `/admin/${p.slug}/plans`, label: `${p.name} · Plans`, icon: "◍" },
        ]),
      });
    }

    if (me.is_superadmin) {
      out.push({
        label: "Estate",
        items: [
          { to: "/estate/accounts", label: "Accounts", icon: "◉" },
          { to: "/estate/platforms", label: "Platforms", icon: "▦" },
          { to: "/estate/clients", label: "OAuth clients", icon: "⬡" },
          { to: "/estate/keys", label: "Signing keys", icon: "⚿" },
          { to: "/estate/audit", label: "Audit", icon: "≡" },
        ],
      });
    }

    return out;
  }, [me.is_superadmin, platforms]);

  return (
    <div className={`shell ${collapsed ? "collapsed" : ""} ${railOpen ? "rail-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">H</span>
          <span className="brand-text">
            <span className="brand-name">Hynt</span>
            <span className="brand-tag">Accounts</span>
          </span>
          <button
            className="rail-toggle"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            title={collapsed ? "Expand" : "Collapse"}
          >
            {collapsed ? "»" : "«"}
          </button>
        </div>

        <nav className="nav">
          {groups.map((g) => (
            <div className="nav-group" key={g.label}>
              <div className="nav-label">{g.label}</div>
              {g.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                  // The label is the tooltip only when it is the sole thing a
                  // collapsed rail can show; expanded, the text is right there.
                  title={collapsed ? item.label : undefined}
                  onClick={() => setRailOpen(false)}
                >
                  <span className="ic" aria-hidden="true">{item.icon}</span>
                  <span className="label">{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="rail-foot">
          <span className="muted">One account for every Hynt platform</span>
        </div>
      </aside>

      <header className="topbar">
        <button
          className="rail-toggle in-top"
          onClick={() => setRailOpen((o) => !o)}
          aria-expanded={railOpen}
          aria-label="Navigation"
        >
          ☰
        </button>

        <div className="top-spacer" />

        <div className="who">
          <div className="who-text">
            <span className="who-name">
              {me.full_name || me.email}
              {me.is_superadmin && <span className="chip small">superadmin</span>}
            </span>
            <span className="who-email">{me.email}</span>
          </div>
          <AppearanceButton />
          <button className="btn ghost" onClick={onSignOut}>Sign out</button>
        </div>
      </header>

      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
