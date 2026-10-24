// Browser sign-in with OpenID Connect: Authorization Code + PKCE (S256), public client, no client secret.
// The access token lives only in memory, so it is never written to browser storage. sessionStorage (cleared when
// the tab closes) keeps just the refresh token, which Keycloak rotates on every use, and the ID token needed for
// logout. The API verifies every access token itself; nothing here is trusted for authorisation.

const PENDING = "awoc.oidc.pending";
const TOKENS = "awoc.oidc.tokens";

const store = {
  get(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || "null");
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: the user signs in again next time */
    }
  },
  remove(key) {
    try {
      sessionStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};

function base64url(bytes) {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(n = 32) {
  return base64url(crypto.getRandomValues(new Uint8Array(n)));
}

export async function pkceChallenge(verifier) {
  return base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
}

function decodePayload(jwt) {
  try {
    const part = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(part.padEnd(part.length + ((4 - (part.length % 4)) % 4), "=")));
  } catch {
    return null;
  }
}

let discovery = null;
async function endpoints(issuer) {
  if (!discovery || discovery.issuer !== issuer) {
    const res = await fetch(`${issuer}/.well-known/openid-configuration`);
    if (!res.ok) throw new Error("Sign-in service is unavailable.");
    discovery = await res.json();
  }
  return discovery;
}

const redirectUri = () => `${window.location.origin}/`;

export async function signIn(config) {
  const ep = await endpoints(config.issuer);
  const verifier = randomString(48);
  const state = randomString(16);
  const nonce = randomString(16);
  store.set(PENDING, { verifier, state, nonce });
  const q = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: redirectUri(),
    scope: "openid",
    state,
    nonce,
    code_challenge: await pkceChallenge(verifier),
    code_challenge_method: "S256",
  });
  window.location.assign(`${ep.authorization_endpoint}?${q}`);
}

let current = null; // { access_token, expires_at } - memory only

// Takes a token response from the provider. Exported for tests.
export function adoptTokens(t) {
  current = { access_token: t.access_token, expires_at: Date.now() + (t.expires_in || 60) * 1000 };
  const kept = store.get(TOKENS) || {};
  store.set(TOKENS, { refresh_token: t.refresh_token || null, id_token: t.id_token || kept.id_token || null });
  return current;
}

async function tokenRequest(config, params) {
  const ep = await endpoints(config.issuer);
  const res = await fetch(ep.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: config.client_id, ...params }),
  });
  if (!res.ok) throw new Error("Sign-in failed.");
  return res.json();
}

// Completes sign-in when the identity provider redirects back with ?code=...&state=...
export async function completeSignIn(config) {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const error = url.searchParams.get("error");
  if (!code && !error) return false;
  const pending = store.get(PENDING);
  store.remove(PENDING);
  window.history.replaceState({}, "", url.pathname);
  if (error) throw new Error("Sign-in was cancelled or refused.");
  if (!pending || url.searchParams.get("state") !== pending.state) throw new Error("Sign-in response did not match this browser session.");
  const t = await tokenRequest(config, {
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri(),
    code_verifier: pending.verifier,
  });
  if (decodePayload(t.id_token)?.nonce !== pending.nonce) throw new Error("Sign-in response failed the replay check.");
  adoptTokens(t);
  return true;
}

let refreshing = null;

// A valid access token, refreshed shortly before expiry; null when the user must sign in again.
export async function accessToken(config) {
  if (current && current.expires_at - Date.now() > 30_000) return current.access_token;
  const refresh = store.get(TOKENS)?.refresh_token;
  if (!refresh) return null; // after a reload this is how the session resumes, or ends
  refreshing ??= tokenRequest(config, { grant_type: "refresh_token", refresh_token: refresh })
    .then((r) => adoptTokens(r).access_token)
    .catch(() => {
      clearSession();
      return null;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export function hasSession() {
  return Boolean(current || store.get(TOKENS)?.refresh_token);
}

export function clearSession() {
  current = null;
  store.remove(TOKENS);
  store.remove(PENDING);
}

export async function signOut(config) {
  const idToken = store.get(TOKENS)?.id_token;
  clearSession();
  try {
    const ep = await endpoints(config.issuer);
    if (ep.end_session_endpoint) {
      const q = new URLSearchParams({ client_id: config.client_id, post_logout_redirect_uri: redirectUri() });
      if (idToken) q.set("id_token_hint", idToken);
      window.location.assign(`${ep.end_session_endpoint}?${q}`);
      return;
    }
  } catch {
    /* provider unreachable: the local session is already gone */
  }
  window.location.assign(redirectUri());
}
