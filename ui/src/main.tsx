import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./errors/ErrorBoundary";
import { installGlobalErrorHandlers } from "./errors/reporting";
import "./styles.css";

installGlobalErrorHandlers();

const container = document.getElementById("root");
if (container === null) {
  throw new Error("The #root element is missing from index.html");
}

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
