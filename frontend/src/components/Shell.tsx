/** Sidebar, top bar and the signed-in chrome. */
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useSession } from "../lib/session";
import { Badge } from "./ui";

function Item({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink to={to} end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      {children}
    </NavLink>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const { user, signOut } = useSession();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">H</span>
          <span>Hynt Accounts</span>
        </div>

        <Item to="/">Platforms</Item>
        <Item to="/plans">Plans &amp; billing</Item>

        <div className="nav-section">Account</div>
        <Item to="/profile">Profile</Item>
        <Item to="/security">Security</Item>

        {user?.is_superadmin ? (
          <>
            <div className="nav-section">Administration</div>
            <Item to="/admin/users">Users</Item>
            <Item to="/admin/platforms">Platforms</Item>
            <Item to="/admin/audit">Audit log</Item>
          </>
        ) : null}
      </aside>

      <div className="main">
        <header className="topbar">
          <div />
          <div className="row">
            <div style={{ textAlign: "right", lineHeight: 1.25 }}>
              <div style={{ fontSize: 13.5, fontWeight: 550 }}>{user?.full_name || user?.email}</div>
              <div className="faint">{user?.email}</div>
            </div>
            {user?.is_superadmin ? <Badge kind="superadmin">superadmin</Badge> : null}
            <button className="btn btn-sm" onClick={() => void signOut()}>Sign out</button>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
