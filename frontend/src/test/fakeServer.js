import { vi } from "vitest";

// Replaces fetch with canned responses: routes = { "GET /api/x": body | (req) => [status, body] }.
export function fakeServer(routes) {
  const calls = [];
  const fetchMock = vi.fn(async (url, init = {}) => {
    const method = init.method || "GET";
    const path = String(url).split("?")[0];
    calls.push({ method, url: String(url), headers: init.headers || {}, body: init.body });
    const handler = routes[`${method} ${path}`];
    let status = 200;
    let body = handler;
    if (typeof handler === "function") [status, body] = handler(init);
    if (handler === undefined) [status, body] = [404, { detail: `no fake for ${method} ${path}` }];
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      json: async () => body,
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
