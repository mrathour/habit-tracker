/**
 * Habit Tracker token service (PLAN.md 12.2): a stateless Cloudflare Worker.
 *
 * - `GET /`, `/privacy`, `/terms`, `/support`: static pages for Notion's developer portal.
 * - `GET /health`: liveness check.
 * - `POST /start`, `GET /callback`, `POST /refresh`, `POST /revoke`: the OAuth routes
 *   (src/oauth.ts, docs/handoff-protocol.md).
 *
 * It stores nothing and logs only the route, method, status, duration and a short reason
 * (src/log.ts).
 */

import { logRequest, routeLabel } from "./log.ts";
import {
  callback,
  type Deps,
  errorJson,
  json,
  type Outcome,
  refresh,
  revoke,
  start,
} from "./oauth.ts";
import {
  htmlResponse,
  ICON,
  ICON_PATH,
  PAGES,
  renderPage,
  STYLESHEET,
  STYLESHEET_PATH,
} from "./pages.ts";

const OAUTH_ROUTES = {
  "/start": start,
  "/callback": callback,
  "/refresh": refresh,
  "/revoke": revoke,
} as const;

const KNOWN_ROUTES: ReadonlySet<string> = new Set([
  ...Object.keys(PAGES),
  STYLESHEET_PATH,
  ICON_PATH,
  "/health",
  ...Object.keys(OAUTH_ROUTES),
]);

/** Sent on every response (PLAN.md 12.2). */
const COMMON_HEADERS: Readonly<Record<string, string>> = {
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Strict-Transport-Security": "max-age=31536000",
};

function withHeaders(response: Response): Response {
  const result = new Response(response.body, response);
  for (const [name, value] of Object.entries(COMMON_HEADERS)) {
    result.headers.set(name, value);
  }
  return result;
}

function isOAuthRoute(pathname: string): pathname is keyof typeof OAUTH_ROUTES {
  return Object.hasOwn(OAUTH_ROUTES, pathname);
}

async function rateLimited(request: Request, limiter: RateLimit): Promise<boolean> {
  // Cloudflare sets CF-Connecting-IP on every request; the counter is keyed by it only.
  const key = request.headers.get("CF-Connecting-IP") ?? "unknown";
  const { success } = await limiter.limit({ key });
  return !success;
}

async function route(request: Request, env: Env, deps: Deps): Promise<Outcome> {
  const { pathname } = new URL(request.url);

  if (isOAuthRoute(pathname)) {
    if (await rateLimited(request, env.OAUTH_LIMITER)) {
      return errorJson(429, "rate_limited", "Too many requests. Wait a minute and try again.");
    }
    return OAUTH_ROUTES[pathname](request, env, deps);
  }

  const page = PAGES[pathname];
  const isStatic =
    page !== undefined ||
    pathname === STYLESHEET_PATH ||
    pathname === ICON_PATH ||
    pathname === "/health";
  if (!isStatic) return errorJson(404, "not_found", "Not found.");
  if (request.method !== "GET" && request.method !== "HEAD") {
    return errorJson(405, "method_not_allowed", "Use GET.");
  }
  if (await rateLimited(request, env.PAGE_LIMITER)) {
    return errorJson(429, "rate_limited", "Too many requests. Wait a minute and try again.");
  }
  if (page !== undefined) return { response: htmlResponse(renderPage(page)) };
  if (pathname === STYLESHEET_PATH) {
    return {
      response: new Response(STYLESHEET, {
        headers: { "Content-Type": "text/css; charset=utf-8" },
      }),
    };
  }
  if (pathname === ICON_PATH) {
    return { response: new Response(ICON, { headers: { "Content-Type": "image/png" } }) };
  }
  return { response: json({ status: "ok" }) };
}

/** Build the Worker's fetch handler. Tests pass their own `fetch` and clock. */
export function createHandler(deps: Deps) {
  return async (request: Request, env: Env): Promise<Response> => {
    const started = Date.now();
    let outcome: Outcome;
    try {
      outcome = await route(request, env, deps);
    } catch {
      // Never include the error itself: it could carry request data.
      outcome = errorJson(500, "internal_error", "Something went wrong. Please try again.");
      outcome.reason = "unhandled_exception";
    }
    const response = withHeaders(outcome.response);
    logRequest({
      route: routeLabel(new URL(request.url).pathname, KNOWN_ROUTES),
      method: request.method,
      status: response.status,
      durationMs: Date.now() - started,
      ...(outcome.reason === undefined ? {} : { reason: outcome.reason }),
    });
    return response;
  };
}

const handle = createHandler({
  fetch: (input, init) => fetch(input, init),
  now: () => Math.floor(Date.now() / 1000),
});

export default {
  fetch: (request, env) => handle(request, env),
} satisfies ExportedHandler<Env>;
