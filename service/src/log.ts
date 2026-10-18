/**
 * The only logging in the Worker. One line per request, holding the route, the status code and
 * the duration. Never URLs with parameters, request or response bodies, or headers, so no token,
 * code or state can reach a log (PLAN.md 12.2).
 */

export interface RequestLog {
  route: string;
  method: string;
  status: number;
  durationMs: number;
  /** A short machine-readable reason for an error response, never user data. */
  reason?: string;
}

/** Known routes are logged by name; anything else is logged as "other". */
export function routeLabel(pathname: string, knownRoutes: ReadonlySet<string>): string {
  return knownRoutes.has(pathname) ? pathname : "other";
}

export function logRequest(entry: RequestLog): void {
  console.log(JSON.stringify(entry));
}
