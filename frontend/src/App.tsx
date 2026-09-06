import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, type Me } from "./api";
import { Shell } from "./Shell";
import { AdminPage } from "./pages/Admin";
import { LauncherPage } from "./pages/Launcher";
import { LoginPage } from "./pages/Login";
import { SecurityPage } from "./pages/Security";
import { SuperadminPage } from "./pages/Superadmin";

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    try {
      setMe(await api.get<Me>("/api/v1/me"));
    } catch {
      setMe(null);
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
    <Routes>
      <Route path="/login" element={<LoginPage me={me} onSignedIn={refresh} />} />
      <Route
        element={me ? <Shell me={me} onSignOut={signOut} /> : <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />}
      >
        <Route path="/" element={<LauncherPage />} />
        <Route path="/security" element={<SecurityPage me={me!} onChanged={refresh} />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/superadmin" element={<SuperadminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
