import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/hanken-grotesk";
import "@fontsource/jetbrains-mono/400.css";
import App from "./App.jsx";
import "./styles.css";
import "./nebula/nebula.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
import "./nebula/golden.css";
import "./nebula/semantic.css";
