/**
 * The appearance model — themes, fonts and typographic settings, persisted and
 * applied to the document.
 *
 * The whole UI is driven by CSS custom properties, so "applying" an appearance
 * is just writing a handful of tokens and a couple of data-attributes onto the
 * <html> element. Nothing in React needs to re-render for a theme change; the
 * browser repaints from the new tokens. That keeps recolouring instant and keeps
 * every page correct without any of them knowing a palette exists.
 *
 * The list mirrors Intelligence's, plus "hynt" — the ultramarine-on-black
 * identity this host shipped with, kept as a choice rather than the default.
 * The default is "daylight", the same light palette Intelligence opens on.
 *
 * Storage is per-origin: accounts.hynt.one and intelligence.hynt.one are
 * different origins, so a choice made here stays here. Carrying it across the
 * estate would mean putting it on the account, not in localStorage.
 */

export type ThemeMode = "dark" | "light";

export interface ThemeDef {
  id: string;
  name: string;
  mode: ThemeMode;
  /** Three swatch colours for the picker preview: background, accent, text. */
  swatch: [string, string, string];
}

export type FontCategory = "sans" | "serif" | "mono";

export interface FontDef {
  id: string;
  name: string;
  category: FontCategory;
  /** CSS family used for the picker's own preview text. */
  cssFamily: string;
}

export interface AppearanceSettings {
  theme: string;
  font: string;
  /** Base body font size in px, 10–22. */
  fontSize: number;
  /** Body font weight: 400 / 500 / 600 / 700. */
  fontWeight: number;
  italic: boolean;
  /** Letter spacing in px, roughly -0.6 to +1.2. */
  tracking: number;
  /** Line-height multiplier, 1.2–1.9. */
  lineHeight: number;
  /** Corner radius in px, 0–16. */
  radius: number;
}

/* ── 17 themes ─────────────────────────────────────────────────────────── */

export const THEMES: ThemeDef[] = [
  // house
  { id: "hynt", name: "Hynt", mode: "dark", swatch: ["#05080f", "#4f8cff", "#eef3fd"] },
  // dark
  { id: "abyss", name: "Abyss", mode: "dark", swatch: ["#0b0d10", "#4c9aff", "#e6edf3"] },
  { id: "midnight", name: "Midnight", mode: "dark", swatch: ["#060b18", "#6cb0ff", "#e8f1ff"] },
  { id: "carbon", name: "Carbon", mode: "dark", swatch: ["#0f0f11", "#9aa0a6", "#ececef"] },
  { id: "tokyo-night", name: "Tokyo Night", mode: "dark", swatch: ["#1a1b26", "#7aa2f7", "#c0caf5"] },
  { id: "dracula", name: "Dracula", mode: "dark", swatch: ["#282a36", "#bd93f9", "#f8f8f2"] },
  { id: "nord", name: "Nord", mode: "dark", swatch: ["#2e3440", "#88c0d0", "#eceff4"] },
  { id: "mocha", name: "Mocha", mode: "dark", swatch: ["#1e1e2e", "#89b4fa", "#cdd6f4"] },
  { id: "forest", name: "Forest", mode: "dark", swatch: ["#0d1612", "#6fe0a4", "#e6f2ea"] },
  // light
  { id: "daylight", name: "Daylight", mode: "light", swatch: ["#ffffff", "#1b57c4", "#14202e"] },
  { id: "paper", name: "Paper", mode: "light", swatch: ["#fbf8f1", "#a8541b", "#2c2618"] },
  { id: "solar-light", name: "Solar Light", mode: "light", swatch: ["#fdf6e3", "#268bd2", "#3b352a"] },
  { id: "gruvbox-light", name: "Gruvbox Light", mode: "light", swatch: ["#fbf1c7", "#b57614", "#3c3836"] },
  { id: "latte", name: "Latte", mode: "light", swatch: ["#eff1f5", "#1e66f5", "#4c4f69"] },
  { id: "rose-dawn", name: "Rosé Dawn", mode: "light", swatch: ["#faf4ed", "#907aa9", "#575279"] },
  { id: "sand", name: "Sand", mode: "light", swatch: ["#f6f3ee", "#b06a2e", "#2f2a22"] },
  { id: "mist", name: "Mist", mode: "light", swatch: ["#f3f5f7", "#2d6a8e", "#1f2a33"] },
];

/* ── 8 fonts ───────────────────────────────────────────────────────────── */

export const FONTS: FontDef[] = [
  { id: "system", name: "System Sans", category: "sans", cssFamily: "system-ui, sans-serif" },
  { id: "inter", name: "Inter", category: "sans", cssFamily: "'Inter', sans-serif" },
  { id: "plex", name: "IBM Plex Sans", category: "sans", cssFamily: "'IBM Plex Sans', sans-serif" },
  { id: "roboto", name: "Roboto", category: "sans", cssFamily: "'Roboto', sans-serif" },
  { id: "jetbrains", name: "JetBrains Mono", category: "mono", cssFamily: "'JetBrains Mono', monospace" },
  { id: "fira", name: "Fira Code", category: "mono", cssFamily: "'Fira Code', monospace" },
  { id: "georgia", name: "Georgia", category: "serif", cssFamily: "Georgia, serif" },
  { id: "lora", name: "Lora", category: "serif", cssFamily: "'Lora', Georgia, serif" },
];

/* ── defaults + ranges ─────────────────────────────────────────────────── */

export const DEFAULT_APPEARANCE: AppearanceSettings = {
  theme: "daylight",
  font: "system",
  fontSize: 14,
  fontWeight: 400,
  italic: false,
  tracking: 0,
  lineHeight: 1.5,
  radius: 10,
};

export const FONT_SIZE_MIN = 10;
export const FONT_SIZE_MAX = 22;

export const RADIUS_MIN = 0;
export const RADIUS_MAX = 16;

export const FONT_WEIGHTS = [400, 500, 600, 700] as const;
export const LINE_HEIGHTS = [
  { value: 1.25, label: "Compact" },
  { value: 1.5, label: "Cozy" },
  { value: 1.7, label: "Roomy" },
] as const;
export const TRACKINGS = [
  { value: -0.4, label: "Tight" },
  { value: 0, label: "Normal" },
  { value: 0.6, label: "Wide" },
] as const;

export const APPEARANCE_KEY = "hynt.accounts.appearance.v1";

/* ── persistence ───────────────────────────────────────────────────────── */

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Merge stored partial settings onto the defaults, clamping every value. */
export function normalizeSettings(input: unknown): AppearanceSettings {
  const s = (input && typeof input === "object" ? input : {}) as Partial<AppearanceSettings>;
  const themeValid = THEMES.some((t) => t.id === s.theme);
  const fontValid = FONTS.some((f) => f.id === s.font);
  const weight = FONT_WEIGHTS.includes(s.fontWeight as (typeof FONT_WEIGHTS)[number])
    ? (s.fontWeight as number)
    : DEFAULT_APPEARANCE.fontWeight;
  return {
    theme: themeValid ? (s.theme as string) : DEFAULT_APPEARANCE.theme,
    font: fontValid ? (s.font as string) : DEFAULT_APPEARANCE.font,
    fontSize: clamp(Number(s.fontSize) || DEFAULT_APPEARANCE.fontSize, FONT_SIZE_MIN, FONT_SIZE_MAX),
    fontWeight: weight,
    italic: typeof s.italic === "boolean" ? s.italic : DEFAULT_APPEARANCE.italic,
    tracking: typeof s.tracking === "number" ? s.tracking : DEFAULT_APPEARANCE.tracking,
    lineHeight: typeof s.lineHeight === "number" ? s.lineHeight : DEFAULT_APPEARANCE.lineHeight,
    radius:
      typeof s.radius === "number"
        ? clamp(s.radius, RADIUS_MIN, RADIUS_MAX)
        : DEFAULT_APPEARANCE.radius,
  };
}

export function loadSettings(): AppearanceSettings {
  try {
    const raw = localStorage.getItem(APPEARANCE_KEY);
    if (!raw) return DEFAULT_APPEARANCE;
    return normalizeSettings(JSON.parse(raw));
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function saveSettings(settings: AppearanceSettings): void {
  try {
    localStorage.setItem(APPEARANCE_KEY, JSON.stringify(settings));
  } catch {
    /* private mode / quota — not worth disrupting the session over. */
  }
}

/* ── application ───────────────────────────────────────────────────────── */

const THEME_MODE: Record<string, ThemeMode> = Object.fromEntries(
  THEMES.map((t) => [t.id, t.mode]),
);

/** Write the appearance onto <html> as data-attributes and CSS variables. */
export function applyAppearance(settings: AppearanceSettings): void {
  const el = document.documentElement;
  el.dataset.theme = settings.theme;
  el.dataset.font = settings.font;

  const s = el.style;
  s.setProperty("--fs-base", `${settings.fontSize}px`);
  s.setProperty("--font-weight", String(settings.fontWeight));
  s.setProperty("--tracking", `${settings.tracking}px`);
  s.setProperty("--lh", String(settings.lineHeight));
  s.setProperty("--radius", `${settings.radius}px`);
  s.setProperty("--font-style", settings.italic ? "italic" : "normal");

  // Native form controls and scrollbars pick up the palette's light/dark mode.
  const mode = THEME_MODE[settings.theme] ?? "light";
  s.colorScheme = mode;
  // Also exposed as an attribute, because `color-scheme` is not selectable in
  // CSS and some rules need a light/dark hook that does not care *which* of the
  // seventeen themes is active, only which band it sits in.
  el.dataset.mode = mode;
}
