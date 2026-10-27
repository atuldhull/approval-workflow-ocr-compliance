import { vi } from "vitest";

// Replaces fetch with canned responses: routes = { "GET /api/x": body | (req) => [status, body] | Promise of that }.
// A Blob body is served as a file with the Blob's type as its Content-Type.
export function fakeServer(routes) {
  const calls = [];
  const fetchMock = vi.fn(async (url, init = {}) => {
    const method = init.method || "GET";
    const path = String(url).split("?")[0];
    calls.push({ method, url: String(url), headers: init.headers || {}, body: init.body });
    const handler = routes[`${method} ${path}`];
    let status = 200;
    let body = handler;
    if (typeof handler === "function") [status, body] = await handler(init);
    if (handler === undefined) [status, body] = [404, { detail: `no fake for ${method} ${path}` }];
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      headers: { get: (name) => (name.toLowerCase() === "content-type" ? (body instanceof Blob ? body.type : "application/json") : null) },
      json: async () => {
        if (body instanceof Blob) throw new SyntaxError("not JSON");
        return body;
      },
      blob: async () => (body instanceof Blob ? body : new Blob([JSON.stringify(body)], { type: "application/json" })),
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
