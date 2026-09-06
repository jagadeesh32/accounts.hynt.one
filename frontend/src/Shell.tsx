import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import type { Me } from "./api";
import { Avatar, Icon } from "./ui";

export function Shell({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">H</span>
          <span className="brand-name">Hynt Accounts</span>
        </div>

        <nav className="nav" aria-label="Primary">
          <NavLink to="/" end>
            <Icon name="grid-apps" size={14} />Platforms
          </NavLink>
          <NavLink to="/security">
            <Icon name="shield" size={14} />Security
          </NavLink>
          <NavLink to="/admin">
            <Icon name="users" size={14} />Admin
          </NavLink>
          {me.is_superadmin && (
            <NavLink to="/superadmin">
              <Icon name="layers" size={14} />Estate
            </NavLink>
          )}
        </nav>

        <div className="who" ref={menuRef}>
          <button
            className={`user-btn ${menuOpen ? "open" : ""}`}
            onClick={() => setMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <Avatar name={me.full_name} email={me.email} size="sm" />
            <span className="who-text">
              <span className="who-name">{me.full_name || me.email}</span>
              <span className="who-email">{me.email}</span>
            </span>
            <span className="chev"><Icon name="chevron-down" size={14} /></span>
          </button>

          {menuOpen && (
            <div className="user-menu" role="menu">
              <div className="um-head">
                <div className="who-name">{me.full_name || me.email}</div>
                <div className="who-email">{me.email}</div>
                <div className="chips" style={{ marginTop: 8 }}>
                  <span className="chip role"><span className="dot" />{me.status}</span>
                  {me.is_superadmin && <span className="chip accent-chip">superadmin</span>}
                </div>
              </div>
              <button className="um-item" role="menuitem" onClick={() => { setMenuOpen(false); window.location.href = "/security"; }}>
                <Icon name="shield" size={15} />Security settings
              </button>
              <button className="um-item danger" role="menuitem" onClick={() => { setMenuOpen(false); onSignOut(); }}>
                <Icon name="log-out" size={15} />Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="main">
        <Outlet />
      </main>

      <footer className="foot">
        <span>One account for Terminal, X-Terminal and Intelligence.</span>
        <span className="mono dim">accounts.hynt.one</span>
      </footer>
    </div>
  );
}
