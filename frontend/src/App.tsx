import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { SessionProvider, useSession } from "./lib/session";
import { LoadingScreen } from "./components/ui";
import Shell from "./components/Shell";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import Dashboard from "./pages/Dashboard";
import Profile from "./pages/Profile";
import Security from "./pages/Security";
import Subscriptions from "./pages/Subscriptions";
import AdminUsers from "./pages/AdminUsers";
import AdminUserDetail from "./pages/AdminUserDetail";
import AdminPlatforms from "./pages/AdminPlatforms";
import AdminAudit from "./pages/AdminAudit";

function Protected({ children, superadmin = false }: { children: JSX.Element; superadmin?: boolean }) {
  const { loading, user } = useSession();
  const location = useLocation();

  if (loading) return <LoadingScreen />;
  if (!user) {
    // Carry where they were headed, so signing in lands them there rather than
    // dumping everyone on the dashboard.
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?returnTo=${next}`} replace />;
  }
  if (superadmin && !user.is_superadmin) return <Navigate to="/" replace />;
  return <Shell>{children}</Shell>;
}

function PublicOnly({ children }: { children: JSX.Element }) {
  const { loading, user } = useSession();
  if (loading) return <LoadingScreen />;
  // A signed-in user hitting /login with a `next` still needs the login page to
  // run its redirect, so only bounce when there is nowhere to continue to.
  const hasNext = new URLSearchParams(window.location.search).has("next");
  if (user && !hasNext) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <SessionProvider>
      <Routes>
        <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />

        <Route path="/" element={<Protected><Dashboard /></Protected>} />
        <Route path="/profile" element={<Protected><Profile /></Protected>} />
        <Route path="/security" element={<Protected><Security /></Protected>} />
        <Route path="/plans" element={<Protected><Subscriptions /></Protected>} />

        <Route path="/admin/users" element={<Protected superadmin><AdminUsers /></Protected>} />
        <Route path="/admin/users/:userId" element={<Protected superadmin><AdminUserDetail /></Protected>} />
        <Route path="/admin/platforms" element={<Protected superadmin><AdminPlatforms /></Protected>} />
        <Route path="/admin/audit" element={<Protected superadmin><AdminAudit /></Protected>} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SessionProvider>
  );
}
