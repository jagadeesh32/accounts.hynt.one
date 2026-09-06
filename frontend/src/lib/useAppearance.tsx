/**
 * React context for the appearance model.
 *
 * A single provider at the root holds the settings, persists them, and applies
 * them to the document whenever they change. Components read or change the
 * settings through `useAppearance()`, and never touch localStorage or the DOM
 * tokens themselves — both of which are this module's only job.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  DEFAULT_APPEARANCE,
  applyAppearance,
  loadSettings,
  saveSettings,
  type AppearanceSettings,
} from "./appearance";

interface AppearanceContextValue {
  settings: AppearanceSettings;
  update: (patch: Partial<AppearanceSettings>) => void;
  reset: () => void;
}

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppearanceSettings>(() => loadSettings());

  // Apply on every change and persist. The inline pre-React script in
  // index.html already paints the first frame; this keeps later edits live and
  // also guarantees correctness if that script ever fails to run.
  useEffect(() => {
    applyAppearance(settings);
    saveSettings(settings);
  }, [settings]);

  const update = useCallback((patch: Partial<AppearanceSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  const reset = useCallback(() => setSettings(DEFAULT_APPEARANCE), []);

  const value = useMemo<AppearanceContextValue>(
    () => ({ settings, update, reset }),
    [settings, update, reset],
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance(): AppearanceContextValue {
  const ctx = useContext(AppearanceContext);
  if (!ctx) throw new Error("useAppearance must be used inside <AppearanceProvider>");
  return ctx;
}
