import { NavLink, Outlet } from "react-router-dom";
import type { Me } from "./api";
import { AppearanceButton } from "./widgets/AppearancePanel";

export function Shell({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">H</span>
          <span className="brand-name">Hynt Accounts</span>
        </div>

        <nav className="nav">
          <NavLink to="/" end>Platforms</NavLink>
          <NavLink to="/security">Security</NavLink>
          <NavLink to="/admin">Admin</NavLink>
          {me.is_superadmin && <NavLink to="/superadmin">Estate</NavLink>}
        </nav>

        <div className="who">
          <div className="who-text">
            <span className="who-name">{me.full_name || me.email}</span>
            <span className="who-email">{me.email}</span>
          </div>
          <AppearanceButton />
          <button className="btn ghost" onClick={onSignOut}>Sign out</button>
        </div>
      </header>

      <main className="main">
        <Outlet />
      </main>

      <footer className="foot">
        One account for Terminal, X-Terminal and Intelligence.
      </footer>
    </div>
  );
}
