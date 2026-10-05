import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { initTheme } from "./components/ThemeToggle";
import App from "./App.tsx";

// Dark DEFAULT: apply stored/default theme before first paint (no flash).
initTheme();

// Routing + QueryClientProvider live inside App.tsx (App must render
// standalone in tests); main.tsx only mounts.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
