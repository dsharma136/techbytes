/**
 * Vite entry: production shows UnderConstruction unless VITE_SITE_LIVE=true.
 * Dev always loads the full App. App is dynamically imported so its API hooks
 * never run while the placeholder is showing.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { UnderConstruction } from "./components/UnderConstruction.jsx";
import "./styles/globals.css";

const siteLive =
  import.meta.env.DEV || import.meta.env.VITE_SITE_LIVE === "true";

const root = ReactDOM.createRoot(document.getElementById("root"));

if (siteLive) {
  import("./App.jsx").then(({ default: App }) => {
    root.render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    );
  });
} else {
  root.render(
    <React.StrictMode>
      <UnderConstruction />
    </React.StrictMode>,
  );
}
