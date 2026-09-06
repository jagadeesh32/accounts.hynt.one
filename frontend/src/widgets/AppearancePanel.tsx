/**
 * Appearance controls — the settings drawer and its trigger button.
 *
 * Two exports:
 *   • <AppearanceButton/>   — a gear button for the shell header and the login
 *                             screen. It only fires an event; it does not own
 *                             drawer state, so it can be dropped anywhere.
 *   • <AppearanceControls/> — the drawer itself. Rendered once, at the app root,
 *                             it owns the open state and opens in response to
 *                             the button's event or Ctrl/Cmd+Shift+A.
 *
 * The drawer reads and writes the appearance context; it never touches tokens
 * directly, so all the application and persistence rules stay in one place.
 */

import { useEffect, useState } from "react";

import {
  DEFAULT_APPEARANCE,
  FONTS,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  FONT_WEIGHTS,
  LINE_HEIGHTS,
  RADIUS_MAX,
  RADIUS_MIN,
  THEMES,
  TRACKINGS,
} from "../lib/appearance";
import { useAppearance } from "../lib/useAppearance";

const OPEN_EVENT = "hynt:open-appearance";

const WEIGHT_LABEL: Record<number, string> = {
  400: "Regular",
  500: "Medium",
  600: "Semibold",
  700: "Bold",
};

/** Gear button — opens the drawer. Usable in either shell. */
export function AppearanceButton() {
  return (
    <button
      type="button"
      className="ap-btn"
      title="Appearance — themes, fonts, size (Ctrl+Shift+A)"
      aria-label="Open appearance settings"
      onClick={() => window.dispatchEvent(new CustomEvent(OPEN_EVENT))}
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
          stroke="currentColor"
          strokeWidth="1.7"
        />
        <path
          d="M19.4 13.5a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V20a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.6 18.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H2a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 3.7 8.6a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H8a1.7 1.7 0 0 0 1-1.56V2a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V8a1.7 1.7 0 0 0 1.56 1H22a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
      <span className="ap-btn-label">Appearance</span>
    </button>
  );
}

export function AppearanceControls() {
  const { settings, update, reset } = useAppearance();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, onOpen);

    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "a") {
        event.preventDefault();
        setOpen((o) => !o);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener(OPEN_EVENT, onOpen);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  // Lock background scroll while the drawer is open.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <div className={`ap-root${open ? " is-open" : ""}`} aria-hidden={!open}>
      <div className="ap-scrim" onClick={() => setOpen(false)} />

      <aside className="ap-drawer" role="dialog" aria-label="Appearance settings" aria-modal="true">
        <header className="ap-header">
          <h2>Appearance</h2>
          <button className="ap-close" aria-label="Close" onClick={() => setOpen(false)}>
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M6 6l12 12M18 6L6 18"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </header>

        <div className="ap-body">
          {/* ── theme ─────────────────────────────────────────────── */}
          <section className="ap-section">
            <div className="ap-section-head">
              <h3>Theme</h3>
              <span className="ap-count">{THEMES.length}</span>
            </div>
            <div className="ap-theme-grid">
              {THEMES.map((theme) => {
                const active = theme.id === settings.theme;
                return (
                  <button
                    key={theme.id}
                    type="button"
                    className={`ap-theme${active ? " is-active" : ""}`}
                    data-mode={theme.mode}
                    onClick={() => update({ theme: theme.id })}
                    title={`${theme.name} · ${theme.mode}`}
                  >
                    <span className="ap-swatches">
                      <span style={{ background: theme.swatch[0] }} />
                      <span style={{ background: theme.swatch[1] }} />
                      <span style={{ background: theme.swatch[2] }} />
                    </span>
                    <span className="ap-theme-name">{theme.name}</span>
                    <svg className="ap-check" width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        d="M5 12.5l4.5 4.5L19 7"
                        stroke="currentColor"
                        strokeWidth="2.6"
                        fill="none"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                );
              })}
            </div>
          </section>

          {/* ── font family ───────────────────────────────────────── */}
          <section className="ap-section">
            <div className="ap-section-head">
              <h3>Font</h3>
              <span className="ap-count">{FONTS.length}</span>
            </div>
            <div className="ap-font-grid">
              {FONTS.map((font) => {
                const active = font.id === settings.font;
                return (
                  <button
                    key={font.id}
                    type="button"
                    className={`ap-font${active ? " is-active" : ""}`}
                    style={{ fontFamily: font.cssFamily }}
                    onClick={() => update({ font: font.id })}
                    title={`${font.name} · ${font.category}`}
                  >
                    <span className="ap-font-sample">Ag</span>
                    <span className="ap-font-name">{font.name}</span>
                    <span className="ap-font-cat">{font.category}</span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* ── size ──────────────────────────────────────────────── */}
          <section className="ap-section">
            <div className="ap-section-head">
              <h3>Font size</h3>
              <span className="ap-value">{settings.fontSize}px</span>
            </div>
            <input
              type="range"
              className="ap-range"
              min={FONT_SIZE_MIN}
              max={FONT_SIZE_MAX}
              step={1}
              value={settings.fontSize}
              onChange={(e) => update({ fontSize: Number(e.target.value) })}
              aria-label="Font size"
            />
            <div className="ap-range-ticks">
              <span>{FONT_SIZE_MIN}</span>
              <span>small · medium · large</span>
              <span>{FONT_SIZE_MAX}</span>
            </div>
            <div className="ap-preview" style={{ fontSize: settings.fontSize }}>
              One account for Terminal, X-Terminal and Intelligence
            </div>
          </section>

          {/* ── weight + italic ───────────────────────────────────── */}
          <section className="ap-section">
            <div className="ap-section-head">
              <h3>Font weight</h3>
            </div>
            <div className="ap-seg">
              {FONT_WEIGHTS.map((w) => (
                <button
                  key={w}
                  type="button"
                  className="ap-seg-btn"
                  data-active={settings.fontWeight === w}
                  style={{ fontWeight: w }}
                  onClick={() => update({ fontWeight: w })}
                >
                  {WEIGHT_LABEL[w]}
                </button>
              ))}
            </div>
            <label className="ap-toggle">
              <input
                type="checkbox"
                checked={settings.italic}
                onChange={(e) => update({ italic: e.target.checked })}
              />
              <span className="ap-toggle-track">
                <span className="ap-toggle-thumb" />
              </span>
              <span>Italic</span>
            </label>
          </section>

          {/* ── letter spacing + line height + radius ─────────────── */}
          <section className="ap-section">
            <div className="ap-section-head">
              <h3>Letter spacing</h3>
            </div>
            <div className="ap-seg">
              {TRACKINGS.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  className="ap-seg-btn"
                  data-active={settings.tracking === t.value}
                  onClick={() => update({ tracking: t.value })}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="ap-section-head" style={{ marginTop: 14 }}>
              <h3>Line height</h3>
            </div>
            <div className="ap-seg">
              {LINE_HEIGHTS.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  className="ap-seg-btn"
                  data-active={settings.lineHeight === t.value}
                  onClick={() => update({ lineHeight: t.value })}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="ap-section-head" style={{ marginTop: 14 }}>
              <h3>Corner radius</h3>
              <span className="ap-value">{settings.radius}px</span>
            </div>
            <input
              type="range"
              className="ap-range"
              min={RADIUS_MIN}
              max={RADIUS_MAX}
              step={1}
              value={settings.radius}
              onChange={(e) => update({ radius: Number(e.target.value) })}
              aria-label="Corner radius"
            />
          </section>
        </div>

        <footer className="ap-foot">
          <button className="ap-reset" onClick={reset}>
            Reset to defaults
          </button>
          <span className="ap-foot-hint">
            {DEFAULT_APPEARANCE.theme} · {DEFAULT_APPEARANCE.fontSize}px
          </span>
        </footer>
      </aside>
    </div>
  );
}
