/**
 * Session context.
 *
 * One fetch of /auth/session at mount decides everything the shell renders.
 * Kept in context rather than refetched per page so a slow network cannot make
 * the app flicker between signed-in and signed-out states.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, type AccessEntry, type User } from "./api";

interface SessionValue {
  loading: boolean;
  user: User | null;
  access: AccessEntry[];
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  setUser: (user: User) => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [access, setAccess] = useState<AccessEntry[]>([]);

  const refresh = useCallback(async () => {
    try {
      const state = await api.session();
      setUser(state.authenticated ? (state.user ?? null) : null);
      setAccess(state.access ?? []);
    } catch {
      // A failed session probe means "not signed in" as far as the UI is
      // concerned; surfacing it as an error would strand the user on a screen
      // with nothing to do.
      setUser(null);
      setAccess([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setAccess([]);
      window.location.assign("/login");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<SessionValue>(
    () => ({ loading, user, access, refresh, signOut, setUser }),
    [loading, user, access, refresh, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside a SessionProvider");
  return value;
}
