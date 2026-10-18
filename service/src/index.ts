/**
 * Habit Tracker token service (PLAN.md 12.2): a stateless Cloudflare Worker.
 *
 * - `GET /`, `/privacy`, `/terms`, `/support`: static pages for Notion's developer portal.
 * - `GET /health`: liveness check.
 * - `POST /start`, `GET /callback`, `POST /refresh`, `POST /revoke`: the OAuth routes (step 3).
 *
 * It stores nothing and logs only the route, status and duration (src/log.ts).
 */

import { logRequest, routeLabel } from "./log.ts";
import { PAGES, renderPage, STYLESHEET, STYLESHEET_PATH } from "./pages.ts";

const OAUTH_ROUTES = ["/start", "/callback", "/refresh", "/revoke"] as const;
const KNOWN_ROUTES: ReadonlySet<string> = new Set([
  ...Object.keys(PAGES),
  STYLESHEET_PATH,
  "/health",
  ...OAUTH_ROUTES,
]);

/** Sent on every response (PLAN.md 12.2). */
const COMMON_HEADERS: Readonly<Record<string, string>> = {
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Strict-Transport-Security": "max-age=31536000",
};

/** Pages have no scripts, forms or third-party content. */
const PAGE_CSP =
  "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

function withHeaders(response: Response): Response {
  const result = new Response(response.body, response);
  for (const [name, value] of Object.entries(COMMON_HEADERS)) {
    result.headers.set(name, value);
  }
  return result;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function errorJson(status: number, error: string, message: string): Response {
  return json({ error, message }, status);
}

function route(request: Request): Response {
  const url = new URL(request.url);
  const { pathname } = url;

  const page = PAGES[pathname];
  if (page !== undefined || pathname === STYLESHEET_PATH || pathname === "/health") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return errorJson(405, "method_not_allowed", "Use GET.");
    }
  }

  if (page !== undefined) {
    return new Response(renderPage(page), {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": PAGE_CSP,
      },
    });
  }
  if (pathname === STYLESHEET_PATH) {
    return new Response(STYLESHEET, { headers: { "Content-Type": "text/css; charset=utf-8" } });
  }
  if (pathname === "/health") {
    return json({ status: "ok" });
  }
  if ((OAUTH_ROUTES as readonly string[]).includes(pathname)) {
    return errorJson(501, "not_implemented", "This route isn't available yet.");
  }
  return errorJson(404, "not_found", "Not found.");
}

export default {
  fetch(request): Response {
    const started = Date.now();
    let response: Response;
    let reason: string | undefined;
    try {
      response = route(request);
    } catch {
      // Never include the error itself: it could carry request data.
      reason = "unhandled_exception";
      response = errorJson(500, "internal_error", "Something went wrong. Please try again.");
    }
    const final = withHeaders(response);
    logRequest({
      route: routeLabel(new URL(request.url).pathname, KNOWN_ROUTES),
      method: request.method,
      status: final.status,
      durationMs: Date.now() - started,
      ...(reason === undefined ? {} : { reason }),
    });
    return final;
  },
} satisfies ExportedHandler<Env>;
