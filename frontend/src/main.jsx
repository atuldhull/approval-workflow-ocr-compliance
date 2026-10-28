import React from "react";

import { createRoot } from "react-dom/client";

import "@fontsource-variable/hanken-grotesk";

import "@fontsource/jetbrains-mono/400.css";

import App from "./App.jsx";

import { ShowcaseGate } from "./showcase/entry.jsx";

import "./styles.css";

// ShowcaseGate renders the public walk-through for #showcase fragments and the app for everything else.

createRoot(document.getElementById("root")).render(

  <React.StrictMode>

    <ShowcaseGate>

      <App />

    </ShowcaseGate>

  </React.StrictMode>

);

import "./operations/operations.css";

import "./operations/semantic.css";

import "./product/product.css";

import "./product/luxury.css";

import './product/atelier.css';

import './product/atmosphere.css';
