import { afterEach, describe, expect, it } from "vitest";
import { clearSession, completeSignIn, safeReturnHash } from "../auth/oidc.js";
import { fakeServer } from "./fakeServer.js";

const CONFIG = { mode: "oidc", issuer: "http://idp/realms/awoc", client_id: "awoc-ui" };
const b64 = (o) => btoa(JSON.stringify(o)).replace(/=+$/, "");

function returningFromProvider(back) {
  sessionStorage.setItem("awoc.oidc.pending", JSON.stringify({ verifier: "v", state: "s1", nonce: "n1", back }));
  history.replaceState(null, "", "/?code=c1&state=s1");
  fakeServer({
    "GET http://idp/realms/awoc/.well-known/openid-configuration": { issuer: CONFIG.issuer, token_endpoint: "http://idp/token" },
    "POST http://idp/token": { access_token: "a", refresh_token: "r", id_token: `h.${b64({ nonce: "n1" })}.s`, expires_in: 300 },
  });
}

afterEach(() => {
  clearSession();
  history.replaceState(null, "", "/");
});

describe("returning to the requested screen after sign-in", () => {
  it("restores a screen or case link and removes the code and state", async () => {
    returningFromProvider("#applications?case=1b2c-3d");
    expect(await completeSignIn(CONFIG)).toBe(true);
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#applications?case=1b2c-3d");
  });

  it("drops anything that is not a plain screen link", async () => {
    returningFromProvider('#inbox"><img src=x onerror=alert(1)>');
    await completeSignIn(CONFIG);
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("");
  });

  it("accepts only the screen and case shapes", () => {
    expect(safeReturnHash("#inbox")).toBe("#inbox");
    expect(safeReturnHash("#applications?case=abc-123")).toBe("#applications?case=abc-123");
    for (const bad of ["", "inbox", "#Inbox", "#inbox?token=x", "#applications?case=a&x=1", "#javascript:alert(1)", undefined]) {
      expect(safeReturnHash(bad)).toBe("");
    }
  });

  it("keeps the replay and session checks: a mismatched state is refused and no hash is restored", async () => {
    returningFromProvider("#inbox");
    history.replaceState(null, "", "/?code=c1&state=other");
    await expect(completeSignIn(CONFIG)).rejects.toThrow(/did not match/);
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("");
  });
});
