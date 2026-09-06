import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type Me } from "./api";
import { Shell, type AdminPlatform } from "./Shell";
import { AppearanceControls } from "./widgets/AppearancePanel";
import { LauncherPage } from "./pages/Launcher";
import { LoginPage } from "./pages/Login";
import { SecurityPage } from "./pages/Security";
import { MembersPage } from "./pages/Members";
import { PlansPage } from "./pages/Plans";
import { EstateLayout } from "./pages/estate/EstateLayout";
import { AccountsPage } from "./pages/estate/Accounts";
import { EstatePlatformsPage } from "./pages/estate/Platforms";
import { ClientsPage } from "./pages/estate/Clients";
import { KeysPage } from "./pages/estate/Keys";
import { AuditPage } from "./pages/estate/Audit";

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  // The rail needs to know which platforms you administer before it can render,
  // so this is fetched with `me` rather than by the Admin pages themselves.
  const [platforms, setPlatforms] = useState<AdminPlatform[]>([]);
  const [ready, setReady] = useState(false);
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    try {
      const who = await api.get<Me>("/api/v1/me");
      setMe(who);
      // Not fatal: someone who administers nothing still gets a console, they
      // just get no Administration group in the rail.
      const admin = await api
        .get<{ platforms: AdminPlatform[] }>("/api/v1/admin/platforms")
        .catch(() => ({ platforms: [] as AdminPlatform[] }));
      setPlatforms(admin.platforms);
    } catch {
      setMe(null);
      setPlatforms([]);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    await api.post("/api/v1/auth/logout").catch(() => undefined);
    setMe(null);
    setPlatforms([]);
    navigate("/login");
  }, [navigate]);

  if (!ready) {
    return (
      <div className="boot">
        <div className="spinner" aria-label="Loading" />
      </div>
    );
  }

  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage me={me} onSignedIn={refresh} />} />
        <Route
          element={
            me
              ? <Shell me={me} platforms={platforms} onSignOut={signOut} />
              : <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
          }
        >
          <Route path="/" element={<LauncherPage me={me!} />} />
          <Route path="/security" element={<SecurityPage me={me!} onChanged={refresh} />} />

          {/* Per-platform administration. The rail links straight to a section,
              so /admin/:slug on its own lands on members rather than 404ing. */}
          <Route path="/admin/:slug" element={<Navigate to="members" replace />} />
          <Route path="/admin/:slug/members" element={<MembersPage />} />
          <Route path="/admin/:slug/plans" element={<PlansPage />} />

          <Route path="/estate" element={<EstateLayout />}>
            <Route index element={<Navigate to="accounts" replace />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="platforms" element={<EstatePlatformsPage />} />
            <Route path="clients" element={<ClientsPage />} />
            <Route path="keys" element={<KeysPage />} />
            <Route path="audit" element={<AuditPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* Mounted once, above the router: the drawer is reachable from the
          login screen as well as from inside the shell. */}
      <AppearanceControls />
    </>
  );
}
