import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { applyAppearance, loadSettings } from "./lib/appearance";
import { AppearanceProvider } from "./lib/useAppearance";
import { ToastProvider } from "./ui";
// Order matters: fonts.css declares the families, styles.css declares the
// tokens, themes.css redefines those tokens per palette so it must land after
// them, kit.css mixes its own tokens from those, and appearance.css styles the
// drawer that sets them.
import "./styles/fonts.css";
import "./styles.css";
import "./styles/themes.css";
import "./styles/kit.css";
import "./styles/appearance.css";
// Last: the data-viz layer defines its own fixed series palette, which must not
// be recoloured by whichever of the seventeen themes is active.
import "./styles/charts.css";

// Paint the saved appearance before React mounts.
//
// This would conventionally be an inline <script> in index.html, which runs
// earlier. It cannot be: this host's CSP is `script-src 'self'` with no hash
// allowance, and widening it on the estate's identity provider to save one
// frame is a bad trade. Running here — module scope, before the first render —
// costs a brief default-theme frame for a returning user who chose something
// else, and nothing at all for everyone else.
applyAppearance(loadSettings());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppearanceProvider>
      <BrowserRouter>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BrowserRouter>
    </AppearanceProvider>
  </StrictMode>,
);
