import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { savedTheme, showTheme } from "./theme";
import "./styles.css";

showTheme(savedTheme());

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
