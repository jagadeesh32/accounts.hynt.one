import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { AppearanceProvider } from "./lib/useAppearance";
// Order matters: themes.css redefines the tokens styles.css declares, so it
// must land after them. appearance.css styles the drawer that sets them.
import "./styles.css";
import "./styles/themes.css";
import "./styles/appearance.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppearanceProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AppearanceProvider>
  </StrictMode>,
);
