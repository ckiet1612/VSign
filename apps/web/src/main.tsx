import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { config } from "./config";
import { trackInputModality } from "./lib/inputModality";
import { isLandingPath, landingHref } from "./lib/appRoutes";
import "./styles.css";
import "./styles/workspace-ui.css";

// The first paint waits (briefly) for the bundled typeface, so a reload never shows fallback glyphs that then reflow.
// Latin, Vietnamese and Latin Extended subsets are separate faces; the sample text pulls in all three.
const FONT_WAIT_MS = 700;
const fontsReady = typeof document !== "undefined" && "fonts" in document
  ? Promise.race([
      document.fonts.load('1em "Plus Jakarta Sans Variable"', "Aaạđ").catch(() => undefined),
      new Promise(resolve => window.setTimeout(resolve, FONT_WAIT_MS)),
    ])
  : Promise.resolve();

trackInputModality();
const root = createRoot(document.getElementById("root")!);
void fontsReady.then(render);

function render() {
  if (!config.publicDemo && window.location.pathname === "/invite") {
    void import("./components/InvitationAcceptance").then(({ InvitationAcceptance }) => {
      root.render(<StrictMode><InvitationAcceptance platformUrl={config.platformHttpUrl} /></StrictMode>);
    });
  } else if (!config.publicDemo && window.location.pathname === "/display") {
    void import("./display/CustomerDisplay").then(({ CustomerDisplay }) => {
      root.render(<StrictMode><CustomerDisplay platformUrl={config.platformHttpUrl} /></StrictMode>);
    });
  } else if (!config.publicDemo && isLandingPath(window.location.pathname, window.location.search)) {
    if (window.location.pathname.replace(/\/+$/, "") === "/landing") {
      window.history.replaceState(window.history.state, "", `${landingHref()}${window.location.search}${window.location.hash}`);
    }
    void import("./landing/LandingPage").then(({ LandingPage }) => {
      root.render(<StrictMode><LandingPage /></StrictMode>);
    });
  } else if (import.meta.env.DEV && !config.publicDemo && window.location.pathname === "/dev-test") {
    void import("./dev-test/DevTestApp").then(({ default: DevTestApp }) => {
      root.render(<StrictMode><DevTestApp /></StrictMode>);
    });
  } else {
    root.render(<StrictMode><App /></StrictMode>);
  }
}
