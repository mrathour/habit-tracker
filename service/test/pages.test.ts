import { exports } from "cloudflare:workers";
import { afterEach, describe, expect, it, vi } from "vitest";

const BASE = "https://habit-tracker.example.workers.dev";

function get(path: string, init?: RequestInit): Promise<Response> {
  return exports.default.fetch(new Request(`${BASE}${path}`, init));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("pages", () => {
  it.each([
    ["/", "Habit Tracker"],
    ["/privacy", "Privacy policy"],
    ["/terms", "Terms of use"],
    ["/support", "Support"],
  ])("%s serves a complete page", async (path, heading) => {
    const response = await get(path);
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    const html = await response.text();
    expect(html).toContain(`<h1>${heading}</h1>`);
    expect(html).toContain('<link rel="stylesheet" href="/style.css">');
    expect(html).not.toMatch(/<script|<form|<iframe/i);
  });

  it("pages link to each other", async () => {
    const html = await (await get("/")).text();
    for (const path of ["/privacy", "/terms", "/support"]) {
      expect(html).toContain(`href="${path}"`);
    }
  });

  it("serves the stylesheet", async () => {
    const response = await get("/style.css");
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/css; charset=utf-8");
    expect(await response.text()).toContain("--accent");
  });

  it("pages forbid scripts, frames and forms", async () => {
    const csp = (await get("/privacy")).headers.get("Content-Security-Policy") ?? "";
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("form-action 'none'");
    expect(csp).not.toContain("script-src");
  });

  it("rejects other methods on pages", async () => {
    expect((await get("/privacy", { method: "POST" })).status).toBe(405);
  });
});

describe("every response", () => {
  it.each(["/", "/style.css", "/health", "/nope", "/callback"])(
    "%s carries the security headers",
    async (path) => {
      const headers = (await get(path)).headers;
      expect(headers.get("Cache-Control")).toBe("no-store");
      expect(headers.get("Referrer-Policy")).toBe("no-referrer");
      expect(headers.get("X-Content-Type-Options")).toBe("nosniff");
    },
  );
});

describe("/health", () => {
  it("reports ok", async () => {
    const response = await get("/health");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });
});

describe("unknown routes", () => {
  it("return 404 JSON", async () => {
    const response = await get("/does-not-exist");
    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({ error: "not_found" });
  });
});

describe("logging", () => {
  it("logs only the route, method, status and duration", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    await get("/callback?code=secret-code-123&state=signed-state-456");
    await get("/private/path?token=abc");
    const lines = log.mock.calls.map((call) => String(call[0]));
    expect(lines).toHaveLength(2);
    for (const line of lines) {
      expect(line).not.toContain("secret-code-123");
      expect(line).not.toContain("signed-state-456");
      expect(line).not.toContain("?");
      expect(Object.keys(JSON.parse(line) as object).sort()).toEqual(
        ["durationMs", "method", "route", "status"].sort(),
      );
    }
    expect(JSON.parse(lines[1] ?? "{}")).toMatchObject({ route: "other" });
  });
});
