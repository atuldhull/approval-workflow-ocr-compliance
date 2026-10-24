import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { clearSession } from "../auth/oidc.js";

afterEach(() => {
  cleanup();
  clearSession(); // the access token lives in module memory
  sessionStorage.clear();
  localStorage.clear();
});
